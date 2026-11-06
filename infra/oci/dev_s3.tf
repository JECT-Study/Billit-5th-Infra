# 개발 업로드 S3 호환 API 전용. 운영/백업 버킷·목록·덮어쓰기 권한은 없다.
# Customer Secret Key는 Terraform으로 만들지 않는다(상태파일에 비밀 저장 방지).
variable "dev_s3_service_email" {
  description = "개발 S3 서비스 계정의 팀 공용 복구 이메일. 로컬 tfvars에만 저장한다."
  type        = string
  sensitive   = true
  default     = null
}

resource "oci_identity_user" "dev_s3" {
  compartment_id = var.tenancy_ocid
  name           = "ject-dev-s3"
  email          = var.dev_s3_service_email
  description    = "JECT development uploads S3 service user"
  freeform_tags  = local.tags
}

resource "oci_identity_user_capabilities_management" "dev_s3" {
  user_id                      = oci_identity_user.dev_s3.id
  can_use_api_keys             = false
  can_use_auth_tokens          = false
  can_use_console_password     = false
  can_use_customer_secret_keys = true
  can_use_smtp_credentials     = false
}

resource "oci_identity_group" "dev_s3" {
  compartment_id = var.tenancy_ocid
  name           = "ject-dev-s3"
  description    = "JECT development upload objects only"
  freeform_tags  = local.tags
}

resource "oci_identity_user_group_membership" "dev_s3" {
  user_id  = oci_identity_user.dev_s3.id
  group_id = oci_identity_group.dev_s3.id
}

resource "oci_identity_policy" "dev_s3" {
  compartment_id = oci_identity_compartment.ject.id
  name           = "ject-dev-s3-uploads"
  description    = "Create read delete development upload objects only"
  statements = [
    "Allow group ${oci_identity_group.dev_s3.name} to manage objects in compartment JECT where all {target.bucket.name = 'ject-dev-uploads', any {request.permission = 'OBJECT_CREATE', request.permission = 'OBJECT_READ', request.permission = 'OBJECT_DELETE'}}",
  ]
  freeform_tags = local.tags
}
