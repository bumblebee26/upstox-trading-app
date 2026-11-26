# The lakehouse in Databricks Free Edition: inside catalog upx, the schemas bronze, silver and gold, the landing volume the sync
# fills (lakehouse/sync.py), and one pipeline built from pipeline/*.sql. Applied by GitHub Actions after a
# merge to main, once the owner approves the "infra" environment; it signs in with DATABRICKS_HOST and
# DATABRICKS_TOKEN (the token is created by the owner and never sits in Terraform state).
provider "databricks" {}

locals {
  repo_root      = "${path.module}/../.."
  pipeline_files = fileset(local.repo_root, "pipeline/*.sql")
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

resource "databricks_pipeline" "lakehouse" {
  name        = "upx-lakehouse"
  catalog     = data.databricks_catalog.upx.name
  schema      = databricks_schema.layer["silver"].name
  serverless  = true
  continuous  = false # started by the sync, only when new files arrived (Free Edition compute)
  development = false
  channel     = "CURRENT"

  dynamic "library" {
    for_each = databricks_workspace_file.pipeline
    content {
      file {
        path = library.value.path
      }
    }
  }
}

output "pipeline_id" {
  value = databricks_pipeline.lakehouse.id
}
