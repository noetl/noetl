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
    terraform plan -destroy
    ```
