variable "oci_profile" {
  description = "~/.oci/config 프로필 이름 (세션 토큰)"
  type        = string
  default     = "JECT"
}

variable "region" {
  type    = string
  default = "ap-chuncheon-1"
}

variable "tenancy_ocid" {
  description = "테넌시 OCID. tfvars(저장소 제외)에 둔다."
  type        = string
}

variable "vcn_cidr" {
  description = "개인 VCN(10.0.0.0/16)과 겹치지 않는 대역"
  type        = string
  default     = "10.20.0.0/16"
}

variable "admin_username" {
  description = "VM 관리자 리눅스 계정 (인프라 담당자 본인)"
  type        = string
  default     = "seongju"
}

variable "admin_ssh_public_key" {
  description = "관리자 본인의 SSH 공개키 한 줄"
  type        = string
}

variable "bastion_client_cidrs" {
  description = "Bastion 세션을 만들 수 있는 클라이언트 대역. 세션 생성은 IAM과 세션 키로 통제한다."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "create_team_iam" {
  description = "ject-developers 그룹·정책 생성 여부"
  type        = bool
  default     = true
}

variable "alert_email" {
  description = "장애·백업 실패 알림을 받을 이메일(OCI Notifications 구독). tfvars(저장소 제외)에 둔다. 구독 확인 메일의 링크를 눌러야 전달된다."
  type        = string
  sensitive   = true
}

variable "additional_alert_emails" {
  description = "추가 장애 알림 이메일. tfvars에만 저장. 앞뒤 공백·대소문자를 정규화하고 빈값·기존 alert_email 중복은 제외한다. 각 주소의 구독 확인이 필요하다."
  type        = set(string)
  default     = []
  nullable    = false
  sensitive   = true

  validation {
    condition = alltrue([
      for email in var.additional_alert_emails : email == null ? false : (
        trimspace(email) == "" || can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", trimspace(email)))
      )
    ])
    error_message = "추가 이메일에는 빈 문자열 또는 공백 없는 이메일 주소를 지정해야 합니다. null 항목은 허용하지 않습니다."
  }
}
