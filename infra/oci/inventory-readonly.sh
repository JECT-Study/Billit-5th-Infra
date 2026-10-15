#!/usr/bin/env bash
# OCI 읽기 전용 현황 점검 (변경 없음). 결과는 .local/oci-inventory-<날짜>.txt에 저장한다.
#   bash infra/oci/inventory-readonly.sh
set -uo pipefail
P="${OCI_PROFILE:-JECT}"
OCI="${OCI_BIN:-$HOME/.local/bin/oci}"
oci() { "$OCI" --profile "$P" --auth security_token "$@"; }
OUT="$(cd "$(dirname "$0")/../.." && pwd)/.local/oci-inventory-$(date +%Y%m%d-%H%M).txt"
mkdir -p "$(dirname "$OUT")"
T=$(grep -A6 "^\[$P\]" ~/.oci/config | awk -F= '/^tenancy/{print $2}')
R=$(grep -A6 "^\[$P\]" ~/.oci/config | awk -F= '/^region/{print $2}')
{
echo "== $(date) profile=$P region=$R"
echo "== 테넌시·구독"
oci iam tenancy get --tenancy-id "$T" --query 'data.{name:name,home:"home-region-key"}'
oci iam region-subscription list --tenancy-id "$T" --query 'data[].{region:"region-name",home:"is-home-region",status:status}' --output table
oci osub-subscription subscription list --compartment-id "$T" 2>/dev/null | head -40 || echo "(구독 정보 조회 불가)"
echo "== 컴파트먼트"
oci iam compartment list --compartment-id "$T" --all --compartment-id-in-subtree true --query 'data[].{name:name,state:"lifecycle-state",id:id}' --output table
echo "== A1 한도·사용량"
AD=$(oci iam availability-domain list --compartment-id "$T" --query 'data[0].name' --raw-output)
for L in standard-a1-core-count standard-a1-memory-count; do
  oci limits value list --compartment-id "$T" --service-name compute --name "$L" --all --query 'data[].{name:name,ad:"availability-domain",value:value}' --output table
  oci limits resource-availability get --compartment-id "$T" --service-name compute --limit-name "$L" --availability-domain "$AD" --query 'data.{used:used,available:available}'
done
echo "== 블록 볼륨 한도"
oci limits resource-availability get --compartment-id "$T" --service-name block-storage --limit-name total-storage-gb --availability-domain "$AD" --query 'data.{used:used,available:available}' 2>/dev/null
echo "== 모든 컴파트먼트의 인스턴스·볼륨·공인 IP·NLB·VCN"
for C in $T $(oci iam compartment list --compartment-id "$T" --all --compartment-id-in-subtree true --query 'data[?"lifecycle-state"==`ACTIVE`].id' --raw-output | tr -d '[]",'); do
  oci compute instance list --compartment-id "$C" --all --query 'data[?"lifecycle-state"!=`TERMINATED`].{name:"display-name",shape:shape,ocpu:"shape-config".ocpus,mem:"shape-config"."memory-in-gbs",state:"lifecycle-state",created:"time-created"}' --output table 2>/dev/null
  oci bv boot-volume list --compartment-id "$C" --availability-domain "$AD" --all --query 'data[].{name:"display-name",gb:"size-in-gbs",state:"lifecycle-state",vpus:"vpus-per-gb"}' --output table 2>/dev/null
  oci bv volume list --compartment-id "$C" --all --query 'data[?"lifecycle-state"!=`TERMINATED`].{name:"display-name",gb:"size-in-gbs",state:"lifecycle-state"}' --output table 2>/dev/null
  oci bv boot-volume-backup list --compartment-id "$C" --all --query 'data[].{name:"display-name",gb:"unique-size-in-gbs",created:"time-created",type:type}' --output table 2>/dev/null
  oci network public-ip list --compartment-id "$C" --scope REGION --lifetime RESERVED --all --query 'data[].{ip:"ip-address",state:"lifecycle-state",assigned:"assigned-entity-type",name:"display-name"}' --output table 2>/dev/null
  oci nlb network-load-balancer list --compartment-id "$C" --all --query 'data.items[].{name:"display-name",state:"lifecycle-state",ips:"ip-addresses"[].{ip:"ip-address",public:"is-public"}}' 2>/dev/null
  oci network vcn list --compartment-id "$C" --all --query 'data[].{name:"display-name",cidr:"cidr-blocks"}' --output table 2>/dev/null
  oci os bucket list --compartment-id "$C" --all --query 'data[].name' 2>/dev/null
done
echo "== 부트 볼륨 백업 정책 할당"
oci bv volume-backup-policy list --all --query 'data[].{name:"display-name",id:id}' --output table 2>/dev/null
echo "== 이미지 (Ubuntu 24.04 aarch64 최신 3개)"
oci compute image list --compartment-id "$T" --operating-system "Canonical Ubuntu" --operating-system-version "24.04" --shape VM.Standard.A1.Flex --sort-by TIMECREATED --sort-order DESC --limit 3 --query 'data[].{name:"display-name",id:id}' --output table
echo "== IAM: 사용자·그룹·동적그룹·정책 이름"
oci iam user list --compartment-id "$T" --all --query 'data[].{name:name,state:"lifecycle-state",mfa:"is-mfa-activated"}' --output table
oci iam group list --compartment-id "$T" --all --query 'data[].name'
oci iam dynamic-group list --compartment-id "$T" --all --query 'data[].name' 2>/dev/null
oci iam policy list --compartment-id "$T" --all --query 'data[].name'
echo "== 예산"
oci budgets budget list --compartment-id "$T" --all --query 'data[].{name:"display-name",amount:amount,spent:"actual-spend"}' --output table 2>/dev/null
} > "$OUT" 2>&1
chmod 600 "$OUT"
echo "$OUT"
