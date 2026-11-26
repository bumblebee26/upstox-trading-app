# The lakehouse in Databricks Free Edition: inside catalog upx, the schemas bronze, silver and gold, the landing volume the sync
# fills (lakehouse/sync.py), and three PySpark pipelines built from pipeline/<name>/*.py. Applied by GitHub Actions after a
# merge to main, once the owner approves the "infra" environment; it signs in with DATABRICKS_HOST and
# DATABRICKS_TOKEN (the token is created by the owner and never sits in Terraform state).
provider "databricks" {}

locals {
  repo_root      = "${path.module}/../.."
  pipeline_files = fileset(local.repo_root, "pipeline/**/*.py")
  # Each pipeline is run by lakehouse/sync.py only at its own times and only when its folders got new files.
  pipelines = {
    trading = "the real pools (journals, balances) and the Telegram feed; 13:05 and 16:55 IST"
    shadows = "the rule-based paper shadows and NIFTYBEES benchmarks; 17:30 IST"
    market  = "NSE files and the copied history; 20:05 IST"
  }
}

# The catalog itself is made once by the owner in the Databricks UI (Catalog → + → Create catalog, name upx,
# Default Storage): Free Edition lets only the UI pick Default Storage. Terraform manages what is inside it.
data "databricks_catalog" "upx" {
  name = "upx"
}

resource "databricks_schema" "layer" {
  for_each     = toset(["bronze", "silver", "gold"])
  catalog_name = data.databricks_catalog.upx.name
  name         = each.key
  lifecycle {
    prevent_destroy = true
  }
}

resource "databricks_volume" "landing" {
  name         = "landing"
  catalog_name = data.databricks_catalog.upx.name
  schema_name  = databricks_schema.layer["bronze"].name
  volume_type  = "MANAGED"
  comment      = "JSON lines copied from the upx-state bucket by lakehouse/sync.py"
  lifecycle {
    prevent_destroy = true
  }
}

resource "databricks_workspace_file" "pipeline" {
  for_each = local.pipeline_files
  source   = "${local.repo_root}/${each.value}"
  path     = "/Workspace/Shared/upx/${each.value}"
}

resource "databricks_pipeline" "layer" {
  for_each    = local.pipelines
  name        = "upx-${each.key}"
  catalog     = data.databricks_catalog.upx.name
  schema      = databricks_schema.layer["silver"].name
  serverless  = true
  continuous  = false # started by the sync, only when its own files are new (Free Edition compute)
  development = false
  channel     = "CURRENT"

  configuration = {
    "upx.purpose" = each.value
  }

  dynamic "library" {
    for_each = { for k, f in databricks_workspace_file.pipeline : k => f if startswith(k, "pipeline/${each.key}/") }
    content {
      file {
        path = library.value.path
      }
    }
  }
}

output "pipeline_ids" {
  value = { for k, p in databricks_pipeline.layer : k => p.id }
}

# ---- History from the old system (files only; PR 10b) ----------------------------------------------------------
resource "databricks_volume" "history" {
  name         = "history"
  catalog_name = data.databricks_catalog.upx.name
  schema_name  = databricks_schema.layer["bronze"].name
  volume_type  = "MANAGED"
  comment      = "One-time copy of the old NSE, US and macro history files (lakehouse/history_copy.py)"
  lifecycle {
    prevent_destroy = true
  }
}

resource "databricks_workspace_file" "history_copy" {
  source = "${local.repo_root}/lakehouse/history_copy.py"
  path   = "/Workspace/Shared/upx/lakehouse/history_copy.py"
}

# Run by hand from GitHub (.github/workflows/history.yml); removed once the copy is checked.
resource "databricks_job" "history_copy" {
  name = "upx-history-copy"

  environment {
    environment_key = "default"
    spec {
      client = "2"
    }
  }

  task {
    task_key        = "copy"
    environment_key = "default"
    spark_python_task {
      python_file = databricks_workspace_file.history_copy.path
    }
  }
}
