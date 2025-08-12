# How to create a Google Cloud Compute Engine VM instance using Terraform

1. Prerequisites

- Ensure billing is enabled on your GCP project (manual).
- Enable the Compute Engine API in your project (manual).
- Install Terraform (v1.x or later recommended) and Google Cloud SDK (for authentication).
    ```bash
    # Authenticate with GCP:
    gcloud auth application-default login
    ```

    ```bash
    gcloud config get-value compute/zone --project noetl-demo-19700101
    (unset)
    ```

2. Set up your Terraform configuration directory
Create a new folder for your Terraform files. For example:
    ```bash
    mkdir tf-gcp-vm
    cd tf-gcp-vm
    ```

3. Create the main Terraform configuration `main.tf`.
Write this basic configuration to create a VM in the default VPC.

    ```tf
    provider "google" {
        project = "PROJECT_ID"
        region  = "REGION"
        zone    = "ZONE"
    }

    resource "google_compute_instance" "tf-example" {
        name         = "tf-example"
        machine_type = "n1-standard-1"
        zone         = "ZONE"

        boot_disk {
            initialize_params {
            image = "debian-cloud/debian-11"
            }
        }

        network_interface {
            network = "default"
            access_config {}
        }
    }
    ```

4. Optional - Create `variables.tf` to use variables.

5. Initialize Terraform

    ```bash
    terraform init
    ```

    This downloads the required providers and sets up Terraform’s working directory. 
    Expected output looks like this:
    ```tf
    Initializing the backend...
    Initializing provider plugins...
    - Finding latest version of hashicorp/google...
    - Installing hashicorp/google v6.47.0...
    - Installed hashicorp/google v6.47.0 (signed by HashiCorp)
    Terraform has created a lock file .terraform.lock.hcl to record the provider
    selections it made above. Include this file in your version control repository
    so that Terraform can guarantee to make the same selections by default when
    you run "terraform init" in the future.

    Terraform has been successfully initialized!

    You may now begin working with Terraform. Try running "terraform plan" to see
    any changes that are required for your infrastructure. All Terraform commands
    should now work.

    If you ever set or change modules or backend configuration for Terraform,
    rerun this command to reinitialize your working directory. If you forget, other
    commands will detect it and remind you to do so if necessary.
    ```

6. Preview the execution plan

    ```bash
    terraform plan

    # To output the plan into a txt file 
    terraform plan -no-color > plan.txt
    ```
    This will show what change will be made.



7. Apply the configuration

    ```bash
    terraform apply
    ```
    Terraform provisions your change.
    Expected output looks like this:
    ```tf
    Terraform used the selected providers to generate the following execution plan. Resource actions are indicated with the following symbols:
    + create

    Terraform will perform the following actions:

    # google_compute_instance.tf-example-vm will be created
    + resource "google_compute_instance" "tf-example-vm" {
        + can_ip_forward       = false
        + cpu_platform         = (known after apply)
        + creation_timestamp   = (known after apply)
        + current_status       = (known after apply)
        + deletion_protection  = false
        + effective_labels     = {
            + "goog-terraform-provisioned" = "true"
            }
        + id                   = (known after apply)
        + instance_id          = (known after apply)
        + label_fingerprint    = (known after apply)
        + machine_type         = "e2-micro"
        + metadata_fingerprint = (known after apply)
        + min_cpu_platform     = (known after apply)
        + name                 = "tf-example-vm"
        + project              = "noetl-demo-19700101"
        + self_link            = (known after apply)
        + tags_fingerprint     = (known after apply)
        + terraform_labels     = {
            + "goog-terraform-provisioned" = "true"
            }
        + zone                 = "us-central1-a"

        + boot_disk {
            + auto_delete                = true
            + device_name                = (known after apply)
            + disk_encryption_key_sha256 = (known after apply)
            + guest_os_features          = (known after apply)
            + kms_key_self_link          = (known after apply)
            + mode                       = "READ_WRITE"
            + source                     = (known after apply)

            + initialize_params {
                + architecture           = (known after apply)
                + image                  = "debian-cloud/debian-11"
                + labels                 = (known after apply)
                + provisioned_iops       = (known after apply)
                + provisioned_throughput = (known after apply)
                + resource_policies      = (known after apply)
                + size                   = (known after apply)
                + snapshot               = (known after apply)
                + type                   = (known after apply)
                }
            }

        + confidential_instance_config (known after apply)

        + guest_accelerator (known after apply)

        + network_interface {
            + internal_ipv6_prefix_length = (known after apply)
            + ipv6_access_type            = (known after apply)
            + ipv6_address                = (known after apply)
            + name                        = (known after apply)
            + network                     = "default"
            + network_attachment          = (known after apply)
            + network_ip                  = (known after apply)
            + stack_type                  = (known after apply)
            + subnetwork                  = (known after apply)
            + subnetwork_project          = (known after apply)

            + access_config {
                + nat_ip       = (known after apply)
                + network_tier = (known after apply)
                }
            }

        + reservation_affinity (known after apply)

        + scheduling (known after apply)
        }

    Plan: 1 to add, 0 to change, 0 to destroy.

    Do you want to perform these actions?
    Terraform will perform the actions described above.
    Only 'yes' will be accepted to approve.

    Enter a value: yes

    google_compute_instance.tf-example-vm: Creating...
    google_compute_instance.tf-example-vm: Still creating... [10s elapsed]
    google_compute_instance.tf-example-vm: Still creating... [20s elapsed]
    google_compute_instance.tf-example-vm: Still creating... [30s elapsed]
    google_compute_instance.tf-example-vm: Creation complete after 39s [id=projects/noetl-demo-19700101/zones/us-central1-a/instances/tf-example-vm]

    Apply complete! Resources: 1 added, 0 changed, 0 destroyed.
    ```

8. Verify the VM

    Check the output in your terminal for completion messages.

    Visit the Google Cloud Console: Compute Engine > VM Instances, and confirm the instance is created.

    [Link](https://console.cloud.google.com/compute/instancesDetail/zones/us-central1-a/instances/tf-example-vm?inv=1&invt=Ab4zpA&project=noetl-demo-19700101)

9. Optional - Destroy the resources to avoid unexpected charges

    First run destroy plan to review what will be destroyed:
    ```bash
    terraform plan -destroy -no-color > plan-destroy.txt
    ```

    To actually destroy the resource:
    ```bash
    terraform destroy
    ```
    Expected output for `terraofrm destroy` looks like this:
   ```tf
    google_compute_instance.tf-example-vm: Refreshing state... [id=projects/noetl-demo-19700101/zones/us-central1-a/instances/tf-example-vm]
    
    Terraform used the selected providers to generate the following execution plan. Resource actions are indicated with the following symbols:
      - destroy
    
    Terraform will perform the following actions:
    
      # google_compute_instance.tf-example-vm will be destroyed
      - resource "google_compute_instance" "tf-example-vm" {
          - can_ip_forward             = false -> null
          - cpu_platform               = "AMD Rome" -> null
          - creation_timestamp         = "2025-08-06T20:25:51.664-07:00" -> null
          - current_status             = "RUNNING" -> null
          - deletion_protection        = false -> null
          - effective_labels           = {
              - "goog-terraform-provisioned" = "true"
            } -> null
          - enable_display             = false -> null
          - id                         = "projects/noetl-demo-19700101/zones/us-central1-a/instances/tf-example-vm" -> null
          - instance_id                = "4346412039371596369" -> null
          - label_fingerprint          = "vezUS-42LLM=" -> null
          - labels                     = {} -> null
          - machine_type               = "e2-micro" -> null
          - metadata                   = {} -> null
          - metadata_fingerprint       = "vFzD5CAeqGU=" -> null
          - name                       = "tf-example-vm" -> null
          - project                    = "noetl-demo-19700101" -> null
          - resource_policies          = [] -> null
          - self_link                  = "https://www.googleapis.com/compute/v1/projects/noetl-demo-19700101/zones/us-central1-a/instances/tf-example-vm" -> null
          - tags                       = [] -> null
          - tags_fingerprint           = "42WmSpB8rSM=" -> null
          - terraform_labels           = {
              - "goog-terraform-provisioned" = "true"
            } -> null
          - zone                       = "us-central1-a" -> null
            # (4 unchanged attributes hidden)
    
          - boot_disk {
              - auto_delete                     = true -> null
              - device_name                     = "persistent-disk-0" -> null
              - force_attach                    = false -> null
              - guest_os_features               = [
                  - "UEFI_COMPATIBLE",
                  - "VIRTIO_SCSI_MULTIQUEUE",
                  - "GVNIC",
                ] -> null
              - mode                            = "READ_WRITE" -> null
              - source                          = "https://www.googleapis.com/compute/v1/projects/noetl-demo-19700101/zones/us-central1-a/disks/tf-example-vm" -> null
                # (6 unchanged attributes hidden)
    
              - initialize_params {
                  - architecture                = "X86_64" -> null
                  - enable_confidential_compute = false -> null
                  - image                       = "https://www.googleapis.com/compute/v1/projects/debian-cloud/global/images/debian-11-bullseye-v20250728" -> null
                  - labels                      = {} -> null
                  - provisioned_iops            = 0 -> null
                  - provisioned_throughput      = 0 -> null
                  - resource_manager_tags       = {} -> null
                  - resource_policies           = [] -> null
                  - size                        = 10 -> null
                  - type                        = "pd-standard" -> null
                    # (2 unchanged attributes hidden)
                }
            }
    
          - network_interface {
              - internal_ipv6_prefix_length = 0 -> null
              - name                        = "nic0" -> null
              - network                     = "https://www.googleapis.com/compute/v1/projects/noetl-demo-19700101/global/networks/default" -> null
              - network_ip                  = "10.128.0.2" -> null
              - queue_count                 = 0 -> null
              - stack_type                  = "IPV4_ONLY" -> null
              - subnetwork                  = "https://www.googleapis.com/compute/v1/projects/noetl-demo-19700101/regions/us-central1/subnetworks/default" -> null
              - subnetwork_project          = "noetl-demo-19700101" -> null
                # (4 unchanged attributes hidden)
    
              - access_config {
                  - nat_ip                 = "35.239.92.15" -> null
                  - network_tier           = "PREMIUM" -> null
                    # (1 unchanged attribute hidden)
                }
            }
    
          - scheduling {
              - automatic_restart           = true -> null
              - availability_domain         = 0 -> null
              - min_node_cpus               = 0 -> null
              - on_host_maintenance         = "MIGRATE" -> null
              - preemptible                 = false -> null
              - provisioning_model          = "STANDARD" -> null
                # (2 unchanged attributes hidden)
            }
    
          - shielded_instance_config {
              - enable_integrity_monitoring = true -> null
              - enable_secure_boot          = false -> null
              - enable_vtpm                 = true -> null
            }
        }
    
    Plan: 0 to add, 0 to change, 1 to destroy.
    
    Do you really want to destroy all resources?
      Terraform will destroy all your managed infrastructure, as shown above.
      There is no undo. Only 'yes' will be accepted to confirm.
    
      Enter a value: yes
    
    google_compute_instance.tf-example-vm: Destroying... [id=projects/noetl-demo-19700101/zones/us-central1-a/instances/tf-example-vm]
    google_compute_instance.tf-example-vm: Still destroying... [id=projects/noetl-demo-19700101/zones/us-central1-a/instances/tf-example-vm, 10s elapsed]
    google_compute_instance.tf-example-vm: Still destroying... [id=projects/noetl-demo-19700101/zones/us-central1-a/instances/tf-example-vm, 20s elapsed]
    google_compute_instance.tf-example-vm: Still destroying... [id=projects/noetl-demo-19700101/zones/us-central1-a/instances/tf-example-vm, 30s elapsed]
    google_compute_instance.tf-example-vm: Still destroying... [id=projects/noetl-demo-19700101/zones/us-central1-a/instances/tf-example-vm, 40s elapsed]
    google_compute_instance.tf-example-vm: Still destroying... [id=projects/noetl-demo-19700101/zones/us-central1-a/instances/tf-example-vm, 50s elapsed]
    google_compute_instance.tf-example-vm: Still destroying... [id=projects/noetl-demo-19700101/zones/us-central1-a/instances/tf-example-vm, 1m0s elapsed]
    google_compute_instance.tf-example-vm: Destruction complete after 1m2s
    
    Destroy complete! Resources: 1 destroyed.
   ```
