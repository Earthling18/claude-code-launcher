terraform {
  required_version = ">= 1.6.0"

  required_providers {
    alicloud = {
      source  = "aliyun/alicloud"
      version = "1.288.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "2.8.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "3.9.0"
    }
  }
}

provider "alicloud" {
  region = var.region
}
