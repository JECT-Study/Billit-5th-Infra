# JECT 전용 OCI 자원. 개인 서버(ssumcp)와 VCN·Compartment·권한을 공유하지 않는다.
# 인증: `oci session authenticate --profile-name JECT` 후 세션 토큰으로 실행한다.

terraform {
  required_version = ">= 1.6.0"
  required_providers {
    oci = {
      source  = "oracle/oci"
      version = "~> 7.0"
    }
  }
}

provider "oci" {
  auth                = "SecurityToken"
  config_file_profile = var.oci_profile
  region              = var.region
}

locals {
  tags = {
    project    = "ject"
    managed_by = "opentofu"
  }
  # 문서의 논리 이름과 실제 리소스 이름을 같게 둔다.
  vms = {
    "ject-prod-app" = {
      subnet    = "public"
      public_ip = true
      nsg       = "prod_app"
      role      = "prod-app"
    }
    "ject-prod-data" = {
      subnet    = "data"
      public_ip = false
      nsg       = "prod_data"
      role      = "prod-data"
    }
    "ject-dev-obs" = {
      subnet    = "dev"
      public_ip = false
      nsg       = "dev"
      role      = "dev"
    }
  }
}

resource "oci_identity_compartment" "ject" {
  compartment_id = var.tenancy_ocid
  name           = "JECT"
  description    = "JECT 5기 3팀 서비스 전용 자원 (개인 프로젝트와 분리)"
  enable_delete  = false
  freeform_tags  = local.tags
}

data "oci_identity_availability_domains" "ads" {
  compartment_id = var.tenancy_ocid
}

data "oci_core_images" "ubuntu_2404_arm" {
  compartment_id           = var.tenancy_ocid
  operating_system         = "Canonical Ubuntu"
  operating_system_version = "24.04"
  shape                    = "VM.Standard.A1.Flex"
  sort_by                  = "TIMECREATED"
  sort_order               = "DESC"
}

locals {
  ad_name = data.oci_identity_availability_domains.ads.availability_domains[0].name
  # Minimal 이미지가 아닌 표준 Ubuntu 24.04 aarch64 이미지 중 최신
  ubuntu_image_id = [
    for img in data.oci_core_images.ubuntu_2404_arm.images : img.id
    if !strcontains(lower(img.display_name), "minimal")
  ][0]
}
