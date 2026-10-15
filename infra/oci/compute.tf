# JECT VM 3대: 각 1 OCPU / 6GB / 부트 50GB, Ubuntu 24.04 aarch64.

resource "oci_bastion_bastion" "ject" {
  compartment_id               = oci_identity_compartment.ject.id
  bastion_type                 = "STANDARD"
  name                         = "jectbastion"
  target_subnet_id             = oci_core_subnet.dev.id
  client_cidr_block_allow_list = var.bastion_client_cidrs
  max_session_ttl_in_seconds   = 10800
  freeform_tags                = local.tags
}

resource "oci_core_instance" "vm" {
  for_each            = local.vms
  compartment_id      = oci_identity_compartment.ject.id
  availability_domain = local.ad_name
  display_name        = each.key
  shape               = "VM.Standard.A1.Flex"

  shape_config {
    ocpus         = 1
    memory_in_gbs = 6
  }

  source_details {
    source_type             = "image"
    source_id               = local.ubuntu_image_id
    boot_volume_size_in_gbs = 50
    boot_volume_vpus_per_gb = 10
  }

  create_vnic_details {
    subnet_id                 = each.value.subnet == "public" ? oci_core_subnet.public.id : (each.value.subnet == "data" ? oci_core_subnet.data.id : oci_core_subnet.dev.id)
    assign_public_ip          = false # 운영 앱은 아래 예약 공인 IP를 붙인다
    nsg_ids                   = [local.nsg_ids[each.value.nsg]]
    hostname_label            = replace(each.key, "ject-", "")
    skip_source_dest_check    = false
    assign_private_dns_record = true
  }

  agent_config {
    are_all_plugins_disabled = false
    is_management_disabled   = false
    is_monitoring_disabled   = false # OCI Monitoring(oci_computeagent 지표) → monitoring.tf의 VM 응답 없음·메모리 알람
    plugins_config {
      name          = "Compute Instance Monitoring"
      desired_state = "ENABLED"
    }
    # A1 + Ubuntu에서는 Bastion 플러그인(관리형 SSH 세션)이 지원되지 않는다. 포트 포워딩 세션만 쓴다.
    plugins_config {
      name          = "Bastion"
      desired_state = "DISABLED"
    }
  }

  instance_options {
    are_legacy_imds_endpoints_disabled = true
  }

  metadata = {
    user_data = base64encode(templatefile("${path.module}/../cloud-init/base.yaml.tftpl", {
      role                 = each.value.role
      hostname             = each.key
      admin_user           = var.admin_username
      admin_ssh_public_key = var.admin_ssh_public_key
    }))
  }

  # 부트 볼륨은 인스턴스를 지워도 남겨 데이터 손실을 막는다.
  preserve_boot_volume = true

  freeform_tags = merge(local.tags, { role = each.value.role })

  lifecycle {
    # 관리자 키 교체는 서버에서 한다(ject-user). 메타데이터 변경으로 VM이 재생성되지 않게 한다.
    ignore_changes  = [source_details[0].source_id, metadata]
    prevent_destroy = true
  }
}

data "oci_core_vnic_attachments" "app" {
  compartment_id = oci_identity_compartment.ject.id
  instance_id    = oci_core_instance.vm["ject-prod-app"].id
}

data "oci_core_private_ips" "app" {
  vnic_id = data.oci_core_vnic_attachments.app.vnic_attachments[0].vnic_id
}

# 예약 공인 IP: VM을 다시 만들어도 DNS를 바꾸지 않도록 고정한다.
resource "oci_core_public_ip" "app" {
  compartment_id = oci_identity_compartment.ject.id
  lifetime       = "RESERVED"
  display_name   = "ject-prod-app-ip"
  private_ip_id  = data.oci_core_private_ips.app.private_ips[0].id
  freeform_tags  = local.tags
  lifecycle {
    prevent_destroy = true
  }
}
