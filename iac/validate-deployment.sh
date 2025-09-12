#!/bin/bash

# Validate NoETL IAC deployment readiness
# This script checks all prerequisites and configurations before deployment

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

TERRAFORM_DIR="terraform"
VALIDATION_PASSED=true
WARNINGS=()
ERRORS=()

print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
    WARNINGS+=("$1")
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
    ERRORS+=("$1")
    VALIDATION_PASSED=false
}

validate_prerequisites() {
    print_status "Validating prerequisites..."

    # Check Terraform
    if ! command -v terraform &> /dev/null; then
        print_error "Terraform is not installed or not in PATH"
    else
        local tf_version
        tf_version=$(terraform version -json | grep -o '"terraform_version":"[^"]*' | cut -d'"' -f4)
        print_success "Terraform version: $tf_version"
    fi

    # Check gcloud
    if ! command -v gcloud &> /dev/null; then
        print_error "Google Cloud SDK (gcloud) is not installed or not in PATH"
    else
        local gcloud_version
        gcloud_version=$(gcloud version --format="value(Google Cloud SDK)" 2>/dev/null || echo "unknown")
        print_success "Google Cloud SDK version: $gcloud_version"
    fi

    # Check Docker
    if ! command -v docker &> /dev/null; then
        print_error "Docker is not installed or not in PATH"
    else
        local docker_version
        docker_version=$(docker --version | cut -d ' ' -f3 | tr -d ',')
        print_success "Docker version: $docker_version"
    fi
}

validate_gcloud_auth() {
    print_status "Validating Google Cloud authentication..."

    if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q .; then
        print_error "Not authenticated with Google Cloud. Run: gcloud auth login"
        return 1
    fi

    local active_account
    active_account=$(gcloud auth list --filter=status:ACTIVE --format="value(account)")
    print_success "Active Google Cloud account: $active_account"

    local current_project
    current_project=$(gcloud config get-value project 2>/dev/null || echo "")
    if [ -z "$current_project" ]; then
        print_warning "No default project set in gcloud config"
    else
        print_success "Current Google Cloud project: $current_project"
    fi
}

validate_project_access() {
    print_status "Validating project access..."

    if [ -f "$TERRAFORM_DIR/terraform.tfvars" ]; then
        local project_id
        project_id=$(grep 'project_id.*=' "$TERRAFORM_DIR/terraform.tfvars" | cut -d'"' -f2 | head -1)

        if [ -n "$project_id" ]; then
            if gcloud projects describe "$project_id" &>/dev/null; then
                print_success "Project access confirmed: $project_id"
            else
                print_error "Cannot access project: $project_id"
            fi
        else
            print_warning "Could not extract project_id from terraform.tfvars"
        fi
    else
        print_warning "terraform.tfvars not found"
    fi
}

validate_terraform_config() {
    print_status "Validating Terraform configuration..."

    if [ ! -d "$TERRAFORM_DIR" ]; then
        print_error "Terraform directory not found: $TERRAFORM_DIR"
        return 1
    fi

    cd "$TERRAFORM_DIR"

    # Check required files
    local required_files=("main.tf" "variables.tf" "infrastructure.tf" "services.tf" "outputs.tf")
    for file in "${required_files[@]}"; do
        if [ ! -f "$file" ]; then
            print_error "Required Terraform file missing: $file"
        else
            print_success "Found: $file"
        fi
    done

    # Check terraform.tfvars
    if [ ! -f "terraform.tfvars" ]; then
        if [ -f "terraform.tfvars.example" ]; then
            print_warning "terraform.tfvars not found. Copy terraform.tfvars.example to terraform.tfvars and configure it"
        else
            print_error "terraform.tfvars.example not found"
        fi
    else
        print_success "Found: terraform.tfvars"
    fi

    # Check terraform.env
    if [ ! -f "terraform.env" ]; then
        print_warning "terraform.env not found. Run setup-terraform-sa.sh to create it"
    else
        print_success "Found: terraform.env"
    fi

    # Validate Terraform syntax
    if terraform validate &>/dev/null; then
        print_success "Terraform configuration syntax valid"
    else
        print_error "Terraform configuration has syntax errors"
        terraform validate
    fi

    cd ..
}

validate_service_account() {
    print_status "Validating service account configuration..."

    cd "$TERRAFORM_DIR"

    if [ -f "terraform.env" ]; then
        # Source the environment file to check credentials
        if source terraform.env 2>/dev/null; then
            if [ -n "$GOOGLE_APPLICATION_CREDENTIALS" ] && [ -f "$GOOGLE_APPLICATION_CREDENTIALS" ]; then
                print_success "Service account key file found: $GOOGLE_APPLICATION_CREDENTIALS"
            else
                print_error "Service account key file not found or not set in terraform.env"
            fi
        else
            print_warning "Could not source terraform.env"
        fi
    else
        print_warning "terraform.env not found"
    fi

    cd ..
}

validate_docker_context() {
    print_status "Validating Docker build context..."

    local dockerfile_path="../docker/noetl/dev/Dockerfile"
    if [ ! -f "$dockerfile_path" ]; then
        print_error "Dockerfile not found: $dockerfile_path"
    else
        print_success "Found Dockerfile: $dockerfile_path"
    fi

    # Check if Docker daemon is running
    if docker info &>/dev/null; then
        print_success "Docker daemon is running"
    else
        print_error "Docker daemon is not running or not accessible"
    fi
}

validate_network_connectivity() {
    print_status "Validating network connectivity..."

    # Check Google Cloud API connectivity
    if curl -s --connect-timeout 5 https://cloudresourcemanager.googleapis.com/v1/projects &>/dev/null; then
        print_success "Google Cloud API connectivity confirmed"
    else
        print_warning "Could not verify Google Cloud API connectivity"
    fi

    # Check Container Registry connectivity
    if curl -s --connect-timeout 5 https://gcr.io &>/dev/null; then
        print_success "Container Registry connectivity confirmed"
    else
        print_warning "Could not verify Container Registry connectivity"
    fi
}

show_deployment_summary() {
    echo ""
    echo "=========================================="
    echo "NoETL IAC Deployment Validation Summary"
    echo "=========================================="
    echo ""

    if [ "$VALIDATION_PASSED" = true ]; then
        print_success "All critical validations passed!"

        if [ ${#WARNINGS[@]} -gt 0 ]; then
            echo ""
            print_warning "Warnings (${#WARNINGS[@]}):"
            for warning in "${WARNINGS[@]}"; do
                echo "  • $warning"
            done
            echo ""
            echo "These warnings should be addressed before production deployment."
        fi

        echo ""
        echo "Next steps:"
        echo "1. Review and update terraform.tfvars with your configuration"
        echo "2. Build container images: ./build-and-deploy.sh --project YOUR_PROJECT_ID"
        echo "3. Deploy infrastructure: ./deploy.sh"

    else
        print_error "Validation failed with ${#ERRORS[@]} error(s)!"
        echo ""
        print_error "Errors:"
        for error in "${ERRORS[@]}"; do
            echo "  • $error"
        done

        if [ ${#WARNINGS[@]} -gt 0 ]; then
            echo ""
            print_warning "Warnings (${#WARNINGS[@]}):"
            for warning in "${WARNINGS[@]}"; do
                echo "  • $warning"
            done
        fi

        echo ""
        echo "Please fix the errors above before attempting deployment."
        exit 1
    fi
}

main() {
    echo "NoETL Infrastructure Validation"
    echo "==============================="
    echo ""

    validate_prerequisites
    validate_gcloud_auth
    validate_project_access
    validate_terraform_config
    validate_service_account
    validate_docker_context
    validate_network_connectivity

    show_deployment_summary
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
