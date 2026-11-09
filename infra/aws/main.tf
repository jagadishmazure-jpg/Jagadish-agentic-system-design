data "aws_caller_identity" "me" {}

data "aws_partition" "p" {}

locals {
  tags      = { app = var.name, data = "synthetic", managed_by = "terraform" }
  model_arn = "arn:${data.aws_partition.p.partition}:bedrock:${var.region}::foundation-model/${var.model_id}"
}

resource "aws_kms_key" "app" {
  description         = "${var.name} logs, secrets and images"
  enable_key_rotation = true
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Sid = "Root", Effect = "Allow", Action = "kms:*", Resource = "*",
      Principal = { AWS = "arn:${data.aws_partition.p.partition}:iam::${data.aws_caller_identity.me.account_id}:root" } },
      { Sid    = "Logs", Effect = "Allow", Resource = "*",
        Action = ["kms:Encrypt*", "kms:Decrypt*", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:Describe*"],
      Principal = { Service = "logs.${var.region}.amazonaws.com" } }
    ]
  })
  tags = local.tags
}

resource "aws_ecr_repository" "app" {
  name                 = var.name
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.app.arn
  }
  tags = local.tags
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/ecs/${var.name}"
  retention_in_days = 365
  kms_key_id        = aws_kms_key.app.arn
  tags              = local.tags
}

resource "aws_secretsmanager_secret" "policy_key" {
  #checkov:skip=CKV2_AWS_57:the HMAC policy key is rotated by a documented manual runbook, not a Lambda
  name       = "${var.name}-policy-key"
  kms_key_id = aws_kms_key.app.arn
  tags       = local.tags
}

data "aws_iam_policy_document" "assume_ecs" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${var.name}-execution"
  assume_role_policy = data.aws_iam_policy_document.assume_ecs.json
  tags               = local.tags
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:${data.aws_partition.p.partition}:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "task" {
  name               = "${var.name}-task"
  assume_role_policy = data.aws_iam_policy_document.assume_ecs.json
  tags               = local.tags
}

data "aws_iam_policy_document" "task" {
  statement {
    sid       = "InvokeOneModel"
    actions   = ["bedrock:InvokeModel", "bedrock:Converse"]
    resources = [local.model_arn]
  }
  statement {
    sid       = "ReadPolicyKey"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.policy_key.arn]
  }
  statement {
    sid       = "DecryptWithAppKey"
    actions   = ["kms:Decrypt"]
    resources = [aws_kms_key.app.arn]
  }
}

resource "aws_iam_role_policy" "task" {
  name   = "${var.name}-task"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task.json
}

resource "aws_ecs_cluster" "app" {
  name = var.name
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
  tags = local.tags
}

resource "aws_ecs_task_definition" "app" {
  family                   = var.name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn
  container_definitions = jsonencode([{
    name                   = "api"
    image                  = "${aws_ecr_repository.app.repository_url}:${var.image_tag}"
    essential              = true
    readonlyRootFilesystem = true
    portMappings           = [{ containerPort = 8080, protocol = "tcp" }]
    environment = [
      { name = "HARROWGATE_PROVIDER", value = "aws" },
      { name = "AWS_MODEL_ID", value = var.model_id }
    ]
    secrets = [{ name = "HARROWGATE_POLICY_KEY", valueFrom = aws_secretsmanager_secret.policy_key.arn }]
    logConfiguration = {
      logDriver = "awslogs"
      options = { awslogs-group = aws_cloudwatch_log_group.app.name, awslogs-region = var.region,
      awslogs-stream-prefix = "api" }
    }
  }])
  tags = local.tags
}

resource "aws_security_group" "app" {
  name        = "${var.name}-svc"
  description = "Service: inbound from the internal load balancer only, outbound HTTPS only"
  vpc_id      = var.vpc_id
  egress {
    description = "HTTPS to AWS APIs through VPC endpoints"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/8"]
  }
  tags = local.tags
}

resource "aws_ecs_service" "app" {
  name            = var.name
  cluster         = aws_ecs_cluster.app.id
  task_definition = aws_ecs_task_definition.app.arn
  desired_count   = 1
  launch_type     = "FARGATE"
  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.app.id]
    assign_public_ip = false
  }
  tags = local.tags
}
