#!/bin/bash

# Deploy NoETL infrastructure using Terraform
# This script automates the deployment process with proper validation and error handling

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

TERRAFORM_DIR="terraform"
TFVARS_FILE=""
AUTO_APPROVE=false
DESTROY=false
PLAN_ONLY=false
INIT_ONLY=false

print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_prerequisites() {
    print_status "Checking prerequisites..."
    
    if ! command -v terraform &> /dev/null; then
        print_error "Terraform is not installed or not in PATH"
        echo "Please install Terraform: https://www.terraform.io/downloads"
        exit 1
    fi
    
    if ! command -v gcloud &> /dev/null; then
        print_error "Google Cloud SDK is not installed or not in PATH"
        echo "Please install gcloud: https://cloud.google.com/sdk/docs/install"
        exit 1
    fi
    
    local tf_version
    tf_version=$(terraform version -json | grep -o '"terraform_version":"[^"]*' | cut -d'"' -f4)
    print_status "Terraform version: $tf_version"
    
    if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q .; then
        print_error "Not authenticated with Google Cloud"
        echo "Please run: gcloud auth login"
        exit 1
    fi
    
    local active_account
    active_account=$(gcloud auth list --filter=status:ACTIVE --format="value(account)")
    print_status "Active Google Cloud account: $active_account"
    
    print_success "Prerequisites check passed"
}

validate_terraform() {
    print_status "Validating Terraform configuration..."
    
    cd "$TERRAFORM_DIR"
    
    terraform validate
    
    if [ -n "$TFVARS_FILE" ] && [ -f "$TFVARS_FILE" ]; then
        print_status "Using variables file: $TFVARS_FILE"
    elif [ -f "terraform.tfvars" ]; then
        TFVARS_FILE="terraform.tfvars"
        print_status "Using default variables file: terraform.tfvars"
    else
        print_warning "No terraform.tfvars file found"
        print_warning "Please copy terraform.tfvars.example to terraform.tfvars and configure it"
        
        if [ ! -f "terraform.tfvars.example" ]; then
            print_error "terraform.tfvars.example not found"
            exit 1
        fi
        
        echo ""
        echo "Would you like me to copy the example file for you? (y/N)"
        read -r response
        if [[ "$response" =~ ^[Yy]$ ]]; then
            cp terraform.tfvars.example terraform.tfvars
            print_success "Copied terraform.tfvars.example to terraform.tfvars"
            print_warning "Please edit terraform.tfvars with your configuration before proceeding"
            exit 0
        else
            exit 1
        fi
    fi
    
    cd ..
    print_success "Terraform validation passed"
}

terraform_init() {
    print_status "Initializing Terraform..."
    
    cd "$TERRAFORM_DIR"
    
    terraform init
    
    cd ..
    print_success "Terraform initialization completed"
}

terraform_plan() {
    print_status "Creating Terraform plan..."
    
    cd "$TERRAFORM_DIR"
    
    local plan_args=()
    if [ -n "$TFVARS_FILE" ]; then
        plan_args+=("-var-file=$TFVARS_FILE")
    fi
    
    if [ "$DESTROY" = true ]; then
        terraform plan -destroy "${plan_args[@]}"
    else
        terraform plan "${plan_args[@]}"
    fi
    
    cd ..
    print_success "Terraform plan completed"
}

terraform_apply() {
    print_status "Applying Terraform configuration..."
    
    cd "$TERRAFORM_DIR"
    
    local apply_args=()
    if [ -n "$TFVARS_FILE" ]; then
        apply_args+=("-var-file=$TFVARS_FILE")
    fi
    
    if [ "$AUTO_APPROVE" = true ]; then
        apply_args+=("-auto-approve")
    fi
    
    if [ "$DESTROY" = true ]; then
        terraform destroy "${apply_args[@]}"
    else
        terraform apply "${apply_args[@]}"
    fi
    
    cd ..
    print_success "Terraform apply completed"
}

show_outputs() {
    if [ "$DESTROY" = true ]; then
        return 0
    fi
    
    print_status "Terraform outputs:"
    
    cd "$TERRAFORM_DIR"
    terraform output
    cd ..
}

show_usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Deploy NoETL infrastructure using Terraform"
    echo ""
    echo "Options:"
    echo "  -f, --tfvars FILE           Path to Terraform variables file"
    echo "  -y, --auto-approve          Skip interactive approval of plan"
    echo "  -d, --destroy               Destroy infrastructure instead of creating"
    echo "  -p, --plan-only             Only run terraform plan"
    echo "  -i, --init-only             Only run terraform init"
    echo "  -h, --help                  Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0                          # Interactive deployment with terraform.tfvars"
    echo "  $0 -f dev.tfvars -y         # Deploy with dev.tfvars, auto-approve"
    echo "  $0 --plan-only              # Only show the plan"
    echo "  $0 --destroy -y             # Destroy infrastructure with auto-approve"
}

while [[ $# -gt 0 ]]; do
    case $1 in
        -f|--tfvars)
            TFVARS_FILE="$2"
            shift 2
            ;;
        -y|--auto-approve)
            AUTO_APPROVE=true
            shift
            ;;
        -d|--destroy)
            DESTROY=true
            shift
            ;;
        -p|--plan-only)
            PLAN_ONLY=true
            shift
            ;;
        -i|--init-only)
            INIT_ONLY=true
            shift
            ;;
        -h|--help)
            show_usage
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            show_usage
            exit 1
            ;;
    esac
done

confirm_destroy() {
    if [ "$DESTROY" = true ] && [ "$AUTO_APPROVE" = false ]; then
        echo ""
        print_warning "You are about to DESTROY the NoETL infrastructure!"
        print_warning "This action cannot be undone and will delete all resources."
        echo ""
        echo "Type 'yes' to confirm destruction:"
        read -r confirmation
        if [ "$confirmation" != "yes" ]; then
            print_status "Destruction cancelled"
            exit 0
        fi
    fi
}

main() {
    echo "NoETL Infrastructure Deployment Script"
    echo "====================================="
    echo ""
    
    if [ "$DESTROY" = true ]; then
        print_warning "DESTROY MODE: Will destroy infrastructure"
    fi
    
    check_prerequisites
    validate_terraform
    terraform_init
    
    if [ "$INIT_ONLY" = true ]; then
        print_success "Initialization completed. Exiting as requested."
        exit 0
    fi
    
    terraform_plan
    
    if [ "$PLAN_ONLY" = true ]; then
        print_success "Plan completed. Exiting as requested."
        exit 0
    fi
    
    confirm_destroy
    terraform_apply
    show_outputs
    
    if [ "$DESTROY" = true ]; then
        print_success "Infrastructure destruction completed!"
    else
        print_success "Infrastructure deployment completed!"
        echo ""
        echo "Next steps:"
        echo "1. Test the server URL shown in the outputs"
        echo "2. Configure your application to use the database connection"
        echo "3. Monitor the services in the Google Cloud Console"
    fi
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
