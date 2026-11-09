// Harrowgate passenger assistant on Azure. WRITTEN, NOT RUN. Same resources as infra/terraform.
// Deploy into an existing resource group: az deployment group create -g <rg> -f main.bicep -p main.parameters.json
targetScope = 'resourceGroup'

@allowed(['dev', 'prod'])
param env string
param location string = resourceGroup().location
@minLength(3)
@maxLength(10)
param prefix string = 'hgasd'
param containerImage string = 'ghcr.io/jagadishmazure-jpg/harrowgate-assistant:0.1.0'
param modelName string = 'gpt-4o-mini'
param modelVersion string = '2024-07-18'
@minValue(1)
@maxValue(50)
param modelCapacity int = 10
param maxReplicas int = 2
param logRetentionDays int = 30
param apiClientId string = '00000000-0000-0000-0000-000000000000'
param tags object = {
  workload: 'harrowgate-assistant'
  owner: 'airport-digital'
  data: 'synthetic'
}

var name = '${prefix}-${env}'
var openAiUserRole = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd' // Cognitive Services OpenAI User
var vaultReaderRole = '4633458b-17de-408a-b874-0445c86b69e6' // built-in role: Key Vault Secrets User (public id)

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-${name}'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: logRetentionDays
  }
}

resource appi 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-${name}'
  location: location
  kind: 'other'
  tags: tags
  properties: {
    Application_Type: 'other'
    WorkspaceResourceId: logs.id
  }
}

resource appId 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-${name}'
  location: location
  tags: tags
}

resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: 'kv-${name}'
  location: location
  tags: tags
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enablePurgeProtection: true
    softDeleteRetentionInDays: 7
    networkAcls: { bypass: 'AzureServices', defaultAction: 'Allow' }
  }
}

resource foundry 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: 'aif-${name}'
  location: location
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  tags: tags
  properties: {
    customSubDomainName: 'aif-${name}'
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
    networkAcls: { defaultAction: 'Allow' }
  }
}

resource chat 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: foundry
  name: 'chat'
  sku: { name: 'GlobalStandard', capacity: modelCapacity }
  properties: {
    model: { format: 'OpenAI', name: modelName, version: modelVersion }
  }
}

resource appModel 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, appId.id, openAiUserRole)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', openAiUserRole)
    principalId: appId.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource appSecrets 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: kv
  name: guid(kv.id, appId.id, vaultReaderRole)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', vaultReaderRole)
    principalId: appId.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource cae 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-${name}'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

resource api 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'ca-${name}'
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${appId.id}': {} }
  }
  properties: {
    managedEnvironmentId: cae.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8080
        transport: 'auto'
      }
    }
    template: {
      scale: { minReplicas: 0, maxReplicas: maxReplicas }
      containers: [
        {
          name: 'api'
          image: containerImage
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
          env: [
            { name: 'HARROWGATE_LLM', value: 'mock' }
            { name: 'FOUNDRY_ENDPOINT', value: foundry.properties.endpoint }
            { name: 'FOUNDRY_DEPLOYMENT', value: chat.name }
            { name: 'AZURE_CLIENT_ID', value: appId.properties.clientId }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appi.properties.ConnectionString }
          ]
          probes: [
            { type: 'Liveness', httpGet: { path: '/healthz', port: 8080 } }
          ]
        }
      ]
    }
  }
}

resource auth 'Microsoft.App/containerApps/authConfigs@2024-03-01' = {
  parent: api
  name: 'current'
  properties: {
    platform: { enabled: true }
    globalValidation: { unauthenticatedClientAction: 'Return401' }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          clientId: apiClientId
          openIdIssuer: '${environment().authentication.loginEndpoint}${subscription().tenantId}/v2.0'
        }
      }
    }
  }
}

resource diagFoundry 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: foundry
  name: 'diag-foundry'
  properties: {
    workspaceId: logs.id
    logs: [{ categoryGroup: 'allLogs', enabled: true }]
  }
}

resource diagKv 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: kv
  name: 'diag-kv'
  properties: {
    workspaceId: logs.id
    logs: [{ category: 'AuditEvent', enabled: true }]
  }
}

output apiFqdn string = api.properties.configuration.ingress.fqdn
output foundryEndpoint string = foundry.properties.endpoint
