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
