provider "google" {
    project = "noetl-demo-19700101"
    region  = var.region
    zone    = "${var.region}-a"
}

resource "google_compute_instance" "tf-example-vm" {
    name          = "tf-example-vm"
    machine_type  = "e2-micro"
    zone          = "${var.region}-a"

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
