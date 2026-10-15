output "compartment_id" {
  value = oci_identity_compartment.ject.id
}

output "bastion_id" {
  value = oci_bastion_bastion.ject.id
}

output "bastion_private_endpoint" {
  value = oci_bastion_bastion.ject.private_endpoint_ip_address
}

output "instances" {
  value = {
    for k, v in oci_core_instance.vm : k => {
      id         = v.id
      private_ip = v.private_ip
      role       = local.vms[k].role
    }
  }
}

output "prod_app_public_ip" {
  value = oci_core_public_ip.app.ip_address
}

output "object_storage_namespace" {
  value = data.oci_objectstorage_namespace.ns.namespace
}

output "ubuntu_image" {
  value = local.ubuntu_image_id
}

output "alert_topic_id" {
  value = oci_ons_notification_topic.alerts.id
}
