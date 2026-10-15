# 비공개 버킷과 인스턴스 주체(Instance Principal) 권한, 팀원 그룹 권한.

data "oci_objectstorage_namespace" "ns" {
  compartment_id = var.tenancy_ocid
}

locals {
  buckets = {
    "ject-prod-uploads" = "운영 업로드 파일"
    "ject-dev-uploads"  = "개발 업로드 파일"
    "ject-db-backups"   = "운영 PostgreSQL 일일 백업"
  }
}

resource "oci_objectstorage_bucket" "b" {
  for_each       = local.buckets
  compartment_id = oci_identity_compartment.ject.id
  namespace      = data.oci_objectstorage_namespace.ns.namespace
  name           = each.key
  access_type    = "NoPublicAccess"
  storage_tier   = "Standard"
  versioning     = "Disabled"
  freeform_tags  = merge(local.tags, { purpose = each.value })
}

# ---- 인스턴스별 동적 그룹 ----------------------------------------------------

resource "oci_identity_dynamic_group" "vm" {
  for_each       = local.vms
  compartment_id = var.tenancy_ocid
  name           = "${each.key}-dg"
  description    = "${each.key} 인스턴스 주체"
  matching_rule  = "instance.id = '${oci_core_instance.vm[each.key].id}'"
  freeform_tags  = local.tags
}

resource "oci_identity_policy" "instances" {
  compartment_id = oci_identity_compartment.ject.id
  name           = "ject-instance-principals"
  description    = "JECT VM별 최소 Object Storage 권한"
  statements = [
    # 운영 데이터 VM: 백업 버킷에만 생성·목록·읽기·삭제(7일 보존 정리). 덮어쓰기(OBJECT_OVERWRITE)는 없음.
    # 남은 위험: 데이터 VM이 탈취되면 백업 삭제가 가능하다(보존 정리를 위해 필요한 권한).
    "Allow dynamic-group ${oci_identity_dynamic_group.vm["ject-prod-data"].name} to read buckets in compartment JECT where target.bucket.name = 'ject-db-backups'",
    "Allow dynamic-group ${oci_identity_dynamic_group.vm["ject-prod-data"].name} to manage objects in compartment JECT where all {target.bucket.name = 'ject-db-backups', any {request.permission = 'OBJECT_CREATE', request.permission = 'OBJECT_INSPECT', request.permission = 'OBJECT_READ', request.permission = 'OBJECT_DELETE'}}",
    # 운영 앱 VM: 운영 업로드 버킷만
    "Allow dynamic-group ${oci_identity_dynamic_group.vm["ject-prod-app"].name} to read buckets in compartment JECT where target.bucket.name = 'ject-prod-uploads'",
    "Allow dynamic-group ${oci_identity_dynamic_group.vm["ject-prod-app"].name} to manage objects in compartment JECT where target.bucket.name = 'ject-prod-uploads'",
    # 개발 VM: 개발 업로드 버킷만 (운영 버킷·백업 접근 불가)
    "Allow dynamic-group ${oci_identity_dynamic_group.vm["ject-dev-obs"].name} to read buckets in compartment JECT where target.bucket.name = 'ject-dev-uploads'",
    "Allow dynamic-group ${oci_identity_dynamic_group.vm["ject-dev-obs"].name} to manage objects in compartment JECT where target.bucket.name = 'ject-dev-uploads'",
  ]
  freeform_tags = local.tags
}

# ---- 팀원(개발자) 그룹: JECT 자원 조회 + Bastion 세션 -----------------------
# 그룹 생성과 정책은 여기서 만들고, 사람의 계정 생성·그룹 가입은 이메일을 받은 뒤
# infra/access/oci-team.md 절차로 한다. 객체(백업·업로드 파일) 내용 읽기는 주지 않는다.

resource "oci_identity_group" "developers" {
  count          = var.create_team_iam ? 1 : 0
  compartment_id = var.tenancy_ocid
  name           = "ject-developers"
  description    = "JECT 개발자: JECT Compartment 조회와 Bastion 세션만"
  freeform_tags  = local.tags
}

resource "oci_identity_policy" "developers" {
  count          = var.create_team_iam ? 1 : 0
  compartment_id = oci_identity_compartment.ject.id
  name           = "ject-developers-access"
  description    = "JECT 개발자 조회·Bastion 접근 (테넌시·개인 자원 권한 없음)"
  statements = [
    "Allow group ${oci_identity_group.developers[0].name} to read instance-family in compartment JECT",
    "Allow group ${oci_identity_group.developers[0].name} to read instance-agent-plugins in compartment JECT",
    "Allow group ${oci_identity_group.developers[0].name} to read virtual-network-family in compartment JECT",
    "Allow group ${oci_identity_group.developers[0].name} to read volume-family in compartment JECT",
    "Allow group ${oci_identity_group.developers[0].name} to read buckets in compartment JECT",
    "Allow group ${oci_identity_group.developers[0].name} to inspect work-requests in compartment JECT",
    "Allow group ${oci_identity_group.developers[0].name} to use bastion in compartment JECT",
    # 개발자는 deploy(CI 전용) 계정으로 세션을 만들 수 없다.
    "Allow group ${oci_identity_group.developers[0].name} to manage bastion-session in compartment JECT where target.bastion-session.username != 'deploy'",
  ]
  freeform_tags = local.tags
}

# ---- CI 배포 주체: 환경별로 분리 -------------------------------------------------
# 각 그룹은 자기 환경 VM에 deploy 계정 세션만 만들 수 있다. 사용자·API 키는 저장소가 정해진 뒤
# 만들고(infra/access/ci-oci-user.md), 키는 GitHub Environment 비밀값으로만 둔다.
locals {
  ci_targets = {
    dev  = "ject-dev-obs"
    prod = "ject-prod-app"
  }
}

resource "oci_identity_group" "ci" {
  for_each       = var.create_team_iam ? local.ci_targets : {}
  compartment_id = var.tenancy_ocid
  name           = "ject-ci-${each.key}"
  description    = "JECT CI 배포(${each.key}): ${each.value}의 deploy 계정 Bastion 세션만"
  freeform_tags  = local.tags
}

resource "oci_identity_policy" "ci" {
  for_each       = var.create_team_iam ? local.ci_targets : {}
  compartment_id = oci_identity_compartment.ject.id
  name           = "ject-ci-${each.key}-deploy"
  description    = "JECT CI(${each.key}) 최소 권한"
  statements = [
    "Allow group ${oci_identity_group.ci[each.key].name} to use bastion in compartment JECT where target.bastion.name = 'jectbastion'",
    "Allow group ${oci_identity_group.ci[each.key].name} to manage bastion-session in compartment JECT where ALL {target.bastion-session.username = 'deploy', target.resource.ocid = '${oci_core_instance.vm[each.value].id}'}",
    "Allow group ${oci_identity_group.ci[each.key].name} to read instances in compartment JECT",
    "Allow group ${oci_identity_group.ci[each.key].name} to read instance-agent-plugins in compartment JECT",
    "Allow group ${oci_identity_group.ci[each.key].name} to inspect work-requests in compartment JECT",
  ]
  freeform_tags = local.tags
}
