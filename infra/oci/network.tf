# VCN 1개, 공개 서브넷 1개(운영 앱), 사설 서브넷 2개(운영 데이터, 개발).
# 접근 제어는 NSG에서 역할별로 한다. Security List는 기본 이그레스만 둔다.

resource "oci_core_vcn" "ject" {
  compartment_id = oci_identity_compartment.ject.id
  display_name   = "ject-vcn"
  cidr_blocks    = [var.vcn_cidr]
  dns_label      = "ject"
  freeform_tags  = local.tags
}

resource "oci_core_internet_gateway" "igw" {
  compartment_id = oci_identity_compartment.ject.id
  vcn_id         = oci_core_vcn.ject.id
  display_name   = "ject-igw"
  enabled        = true
  freeform_tags  = local.tags
}

resource "oci_core_nat_gateway" "nat" {
  compartment_id = oci_identity_compartment.ject.id
  vcn_id         = oci_core_vcn.ject.id
  display_name   = "ject-nat"
  freeform_tags  = local.tags
}

data "oci_core_services" "all" {
  filter {
    name   = "name"
    values = ["All .* Services In Oracle Services Network"]
    regex  = true
  }
}

resource "oci_core_service_gateway" "sgw" {
  compartment_id = oci_identity_compartment.ject.id
  vcn_id         = oci_core_vcn.ject.id
  display_name   = "ject-sgw"
  services {
    service_id = data.oci_core_services.all.services[0].id
  }
  freeform_tags = local.tags
}

resource "oci_core_route_table" "public" {
  compartment_id = oci_identity_compartment.ject.id
  vcn_id         = oci_core_vcn.ject.id
  display_name   = "ject-rt-public"
  route_rules {
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_internet_gateway.igw.id
  }
  freeform_tags = local.tags
}

# 사설 서브넷: 인터넷은 NAT(아웃바운드 전용), OCI 서비스(Object Storage 등)는 Service Gateway
resource "oci_core_route_table" "private" {
  compartment_id = oci_identity_compartment.ject.id
  vcn_id         = oci_core_vcn.ject.id
  display_name   = "ject-rt-private"
  route_rules {
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_nat_gateway.nat.id
  }
  route_rules {
    destination       = data.oci_core_services.all.services[0].cidr_block
    destination_type  = "SERVICE_CIDR_BLOCK"
    network_entity_id = oci_core_service_gateway.sgw.id
  }
  freeform_tags = local.tags
}

# 기본 Security List 대신 이그레스와 Path MTU용 ICMP만 허용하는 목록을 쓴다.
resource "oci_core_security_list" "baseline" {
  compartment_id = oci_identity_compartment.ject.id
  vcn_id         = oci_core_vcn.ject.id
  display_name   = "ject-sl-baseline"
  egress_security_rules {
    destination = "0.0.0.0/0"
    protocol    = "all"
    stateless   = false
  }
  ingress_security_rules {
    source   = "0.0.0.0/0"
    protocol = "1" # ICMP type 3 code 4 (fragmentation needed)
    icmp_options {
      type = 3
      code = 4
    }
  }
  ingress_security_rules {
    source   = var.vcn_cidr
    protocol = "1"
    icmp_options {
      type = 3
    }
  }
  freeform_tags = local.tags
}

resource "oci_core_subnet" "public" {
  compartment_id             = oci_identity_compartment.ject.id
  vcn_id                     = oci_core_vcn.ject.id
  display_name               = "ject-sn-public"
  cidr_block                 = cidrsubnet(var.vcn_cidr, 8, 1)
  dns_label                  = "pub"
  route_table_id             = oci_core_route_table.public.id
  security_list_ids          = [oci_core_security_list.baseline.id]
  prohibit_public_ip_on_vnic = false
  freeform_tags              = local.tags
}

resource "oci_core_subnet" "data" {
  compartment_id             = oci_identity_compartment.ject.id
  vcn_id                     = oci_core_vcn.ject.id
  display_name               = "ject-sn-prod-data"
  cidr_block                 = cidrsubnet(var.vcn_cidr, 8, 2)
  dns_label                  = "data"
  route_table_id             = oci_core_route_table.private.id
  security_list_ids          = [oci_core_security_list.baseline.id]
  prohibit_public_ip_on_vnic = true
  freeform_tags              = local.tags
}

resource "oci_core_subnet" "dev" {
  compartment_id             = oci_identity_compartment.ject.id
  vcn_id                     = oci_core_vcn.ject.id
  display_name               = "ject-sn-dev"
  cidr_block                 = cidrsubnet(var.vcn_cidr, 8, 3)
  dns_label                  = "dev"
  route_table_id             = oci_core_route_table.private.id
  security_list_ids          = [oci_core_security_list.baseline.id]
  prohibit_public_ip_on_vnic = true
  freeform_tags              = local.tags
}

# ---- NSG -----------------------------------------------------------------

resource "oci_core_network_security_group" "prod_app" {
  compartment_id = oci_identity_compartment.ject.id
  vcn_id         = oci_core_vcn.ject.id
  display_name   = "ject-nsg-prod-app"
  freeform_tags  = local.tags
}

resource "oci_core_network_security_group" "prod_data" {
  compartment_id = oci_identity_compartment.ject.id
  vcn_id         = oci_core_vcn.ject.id
  display_name   = "ject-nsg-prod-data"
  freeform_tags  = local.tags
}

resource "oci_core_network_security_group" "dev" {
  compartment_id = oci_identity_compartment.ject.id
  vcn_id         = oci_core_vcn.ject.id
  display_name   = "ject-nsg-dev"
  freeform_tags  = local.tags
}

locals {
  nsg_ids = {
    prod_app  = oci_core_network_security_group.prod_app.id
    prod_data = oci_core_network_security_group.prod_data.id
    dev       = oci_core_network_security_group.dev.id
  }

  # 인바운드 허용 규칙. 여기에 없는 포트는 모두 차단된다.
  ingress_rules = {
    app_http      = { nsg = "prod_app", port = 80, src = "0.0.0.0/0", src_type = "CIDR_BLOCK", desc = "HTTP: HTTPS 리다이렉트, ACME" }
    app_https     = { nsg = "prod_app", port = 443, src = "0.0.0.0/0", src_type = "CIDR_BLOCK", desc = "HTTPS" }
    data_pg       = { nsg = "prod_data", port = 5432, src = "prod_app", src_type = "NSG", desc = "운영 PostgreSQL: 운영 앱 VM만" }
    data_redis    = { nsg = "prod_data", port = 6379, src = "prod_app", src_type = "NSG", desc = "운영 Redis: 운영 앱 VM만" }
    dev_gateway   = { nsg = "dev", port = 8080, src = "prod_app", src_type = "NSG", desc = "개발 게이트웨이: 운영 Nginx만" }
    app_ssh_bast  = { nsg = "prod_app", port = 22, src = "bastion", src_type = "CIDR_BLOCK", desc = "SSH: OCI Bastion 엔드포인트만" }
    data_ssh_bast = { nsg = "prod_data", port = 22, src = "bastion", src_type = "CIDR_BLOCK", desc = "SSH: OCI Bastion 엔드포인트만" }
    dev_ssh_bast  = { nsg = "dev", port = 22, src = "bastion", src_type = "CIDR_BLOCK", desc = "SSH: OCI Bastion 엔드포인트만" }
  }
}

resource "oci_core_network_security_group_security_rule" "ingress" {
  for_each                  = local.ingress_rules
  network_security_group_id = local.nsg_ids[each.value.nsg]
  direction                 = "INGRESS"
  protocol                  = "6"
  description               = each.value.desc
  source_type               = each.value.src_type == "NSG" ? "NETWORK_SECURITY_GROUP" : "CIDR_BLOCK"
  source = (
    each.value.src_type == "NSG" ? local.nsg_ids[each.value.src] :
    each.value.src == "bastion" ? "${oci_bastion_bastion.ject.private_endpoint_ip_address}/32" :
    each.value.src
  )
  stateless = false
  tcp_options {
    destination_port_range {
      min = each.value.port
      max = each.value.port
    }
  }
}

resource "oci_core_network_security_group_security_rule" "egress" {
  for_each                  = local.nsg_ids
  network_security_group_id = each.value
  direction                 = "EGRESS"
  protocol                  = "all"
  destination_type          = "CIDR_BLOCK"
  destination               = "0.0.0.0/0"
  stateless                 = false
}
