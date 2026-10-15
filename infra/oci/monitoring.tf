# 장애 감지(OCI 쪽): 알림 주제·이메일 구독, VM 응답 없음·메모리 알람, 개발 VM의 알림 발행 권한.
# 모두 Always Free 범위다(2026-10-15 공식 가격표 확인): Notifications 이메일 월 1,000건·HTTPS 월 100만 건,
# Monitoring 수집 5억·조회 10억 데이터포인트. OCI Health Checks는 무료 한도가 없어(엔드포인트당 월 $0.30) 쓰지 않는다
# → 외부 접속 확인은 개발 VM의 Alloy가 공인 주소로 시험하고(blackbox), 개발 VM 자체가 죽은 경우는 아래 부재 알람이 잡는다.

resource "oci_ons_notification_topic" "alerts" {
  compartment_id = oci_identity_compartment.ject.id
  name           = "ject-alerts"
  description    = "JECT 장애·백업 실패 알림(OCI 알람 + Grafana 알림 중계)"
  freeform_tags  = local.tags
}

resource "oci_ons_subscription" "alert_email" {
  compartment_id = oci_identity_compartment.ject.id
  topic_id       = oci_ons_notification_topic.alerts.id
  protocol       = "EMAIL"
  endpoint       = var.alert_email
  freeform_tags  = local.tags
}

# Grafana 알림은 개발 VM의 ject-alert-relay(127.0.0.1)가 인스턴스 주체로 이 주제에 발행한다.
# Notifications 정책 조건에는 일반 변수만 쓸 수 있다(target.topic.id 불가 → 실측 404 NotAuthorizedOrNotFound).
# 그래서 JECT 구역의 주제(ject-alerts 하나)에 "발행"만 허용한다. 구독 추가·변경(ONS_TOPIC_SUBSCRIBE 등)은 주지 않는다.
resource "oci_identity_policy" "alert_publish" {
  compartment_id = oci_identity_compartment.ject.id
  name           = "ject-alert-publish"
  description    = "개발·모니터링 VM이 JECT 알림 주제에 발행만"
  statements = [
    "Allow dynamic-group ${oci_identity_dynamic_group.vm["ject-dev-obs"].name} to use ons-topics in compartment JECT where request.permission = 'ONS_TOPIC_PUBLISH'",
  ]
  freeform_tags = local.tags
}

locals {
  vm_alarm_body = "JECT VM의 OCI 에이전트 지표가 5분 넘게 들어오지 않습니다(VM 정지·멈춤·네트워크 단절 가능). 개발 VM이면 Grafana 알림도 멈춘 상태입니다. 확인: bash tools/ject-status.sh, OCI 콘솔 인스턴스 상태."
}

# VM 응답 없음: Compute Instance Monitoring 플러그인의 CPU 지표가 끊기면 울린다(Grafana가 있는 개발 VM이 죽는 사각지대 보완).
resource "oci_monitoring_alarm" "vm_absent" {
  for_each                     = local.vms
  compartment_id               = oci_identity_compartment.ject.id
  metric_compartment_id        = oci_identity_compartment.ject.id
  display_name                 = "ject-${replace(each.key, "ject-", "")}-응답없음"
  namespace                    = "oci_computeagent"
  query                        = "CpuUtilization[1m]{resourceId = \"${oci_core_instance.vm[each.key].id}\"}.absent(72h)"
  severity                     = "CRITICAL"
  pending_duration             = "PT5M"
  resolution                   = "1m"
  body                         = "${each.key}: ${local.vm_alarm_body}"
  message_format               = "ONS_OPTIMIZED"
  repeat_notification_duration = "PT4H"
  destinations                 = [oci_ons_notification_topic.alerts.id]
  is_enabled                   = true
  freeform_tags                = local.tags
}

# 메모리 부족: Grafana 알림(15% 미만)과 별도로, VM 단위 90% 초과가 10분 지속되면 OCI가 직접 알린다.
resource "oci_monitoring_alarm" "vm_memory" {
  compartment_id                                = oci_identity_compartment.ject.id
  metric_compartment_id                         = oci_identity_compartment.ject.id
  display_name                                  = "ject-vm-메모리90"
  namespace                                     = "oci_computeagent"
  query                                         = "MemoryUtilization[5m].groupBy(resourceDisplayName).mean() > 90"
  severity                                      = "WARNING"
  pending_duration                              = "PT10M"
  resolution                                    = "1m"
  body                                          = "JECT VM 메모리 사용률이 90%를 10분 넘게 넘었습니다. Grafana 「JECT 개요」에서 컨테이너·프로세스를 확인하세요."
  message_format                                = "ONS_OPTIMIZED"
  is_notifications_per_metric_dimension_enabled = true
  repeat_notification_duration                  = "PT4H"
  destinations                                  = [oci_ons_notification_topic.alerts.id]
  is_enabled                                    = true
  freeform_tags                                 = local.tags
}
