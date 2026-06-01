# RDS PostgreSQL Database
resource "aws_db_subnet_group" "main" {
  name       = "${var.app_name}-db-subnet-group"
  subnet_ids = [aws_subnet.private_1.id, aws_subnet.private_2.id]

  tags = {
    Name = "${var.app_name}-db-subnet-group"
  }
}

resource "aws_rds_cluster" "main" {
  cluster_identifier      = "${var.app_name}-db-cluster"
  engine                  = "aurora-postgresql"
  engine_version          = "15.2"
  database_name           = "carscanner"
  master_username         = var.rds_username
  master_password         = var.rds_password
  db_subnet_group_name    = aws_db_subnet_group.main.name
  vpc_security_group_ids  = [aws_security_group.rds.id]
  backup_retention_period = 7
  preferred_backup_window = "03:00-04:00"
  skip_final_snapshot     = var.environment != "production"
  
  tags = {
    Name = "${var.app_name}-db-cluster"
  }
}

resource "aws_rds_cluster_instance" "main" {
  cluster_identifier = aws_rds_cluster.main.id
  identifier         = "${var.app_name}-db-instance"
  instance_class     = var.rds_instance_class
  engine             = aws_rds_cluster.main.engine
  engine_version     = aws_rds_cluster.main.engine_version
  
  performance_insights_enabled = var.environment == "production"

  tags = {
    Name = "${var.app_name}-db-instance"
  }
}

# RDS read replica for HA (optional, production only)
resource "aws_rds_cluster_instance" "replica" {
  count              = var.environment == "production" ? 1 : 0
  cluster_identifier = aws_rds_cluster.main.id
  identifier         = "${var.app_name}-db-replica"
  instance_class     = var.rds_instance_class
  engine             = aws_rds_cluster.main.engine
  engine_version     = aws_rds_cluster.main.engine_version

  tags = {
    Name = "${var.app_name}-db-replica"
  }
}
