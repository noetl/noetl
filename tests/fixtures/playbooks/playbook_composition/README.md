# playbook_composition

A comprehensive test demonstrating **playbook composition** with iterators:
- **Main playbook** uses `type: iterator` to process multiple data items
- **Sub-playbook** is called for each iteration to perform complex business logic
- **Result validation** ensures all sub-playbook calls return expected data
- **Data flow** demonstrates passing context between parent and child playbooks
- **PostgreSQL integration** stores results from each iteration

## Architecture Overview

```
Main Playbook (playbook_composition.yaml)
├── Setup PostgreSQL storage table
├── Iterator Step: Process Users
│   ├── For each user in workload.users:
│   │   ├── Call sub-playbook: user_profile_scorer.yaml
│   │   ├── Pass user data + execution context
│   │   ├── Receive profile score + category
│   │   └── Save result to PostgreSQL
│   └── Collect all results
├── Validation Step: Validate Results
│   ├── Check all scores are 0-100 range
│   ├── Verify categories are valid
│   └── Report validation summary
└── End Step: Display completion status

Sub-Playbook (user_profile_scorer.yaml)
├── Extract and validate input user data
├── Calculate weighted scoring components:
│   ├── Experience Score (40% weight)
│   ├── Performance Score (35% weight)
│   ├── Department Score (15% weight)
│   └── Age Factor Score (10% weight)
├── Compute total weighted score
├── Determine category (Junior/Mid-Level/Senior/Executive)
└── Return structured result to parent
```

## Key Features Demonstrated

### 1. **Iterator with Playbook Task**
```yaml
- step: process_users
  type: iterator
  collection: "{{ workload.users }}"
  element: user
  task:
    type: playbook
    path: tests/fixtures/playbooks/playbook_composition/user_profile_scorer
    data:
      user_data: "{{ user }}"
      execution_context: "{{ execution_id }}"
```

### 2. **Workbook Actions in Sub-Playbook**
- Multiple reusable Python functions for scoring calculations
- Structured business logic with clear input/output contracts
- Weighted scoring algorithm with configurable components

### 3. **Data Flow Validation**
```yaml
- step: validate_results
  type: python
  data:
    user_results: "{{ process_users.data }}"
  # Validates all returned scores and categories
```

### 4. **Per-Iteration PostgreSQL Storage**
```yaml
save:
  data:
    id: "{{ execution_id }}:{{ user.name }}"
    profile_score: "{{ this.data.profile_score }}"
    score_category: "{{ this.data.score_category }}"
  storage: postgres
  table: public.user_profile_results
  mode: upsert
```

## Test Scenarios

### Sample Input Data
The main playbook processes 4 users with different profiles:
- **Alice**: Engineering, 5yr exp, 4.2 rating → Expected: Senior/Mid-Level
- **Bob**: Marketing, 8yr exp, 3.8 rating → Expected: Mid-Level
- **Charlie**: Engineering, 3yr exp, 4.5 rating → Expected: Mid-Level  
- **Diana**: Management, 15yr exp, 4.0 rating → Expected: Executive

### Validation Checks
1. **Score Range**: All scores must be 0.0-100.0
2. **Valid Categories**: Junior, Mid-Level, Senior, Executive
3. **Data Structure**: Each result must have required fields
4. **Database Storage**: Results persisted correctly in PostgreSQL

## Testing

## Testing

### Static Tests (Default)
```bash
make test-playbook-composition
```
Tests playbook parsing, planning, and structural validation without runtime execution.

### Runtime Tests with Kubernetes Cluster

#### Prerequisites
- Kubernetes cluster deployed with NoETL (use `task bring-all` to deploy full stack)
- NoETL API accessible on `localhost:8082`
- PostgreSQL accessible on `localhost:54321`

#### Test Commands
```bash
# Register required credentials
task register-test-credentials

# Register playbook composition test
task test-register-playbook-composition

# Execute playbook composition test
task test-execute-playbook-composition

# Full integration test (credentials + register + execute)
task test-playbook-composition-full
```

#### Alias Commands (shorter)
```bash
# Register credentials
task rtc

# Register playbook
task trpc

# Execute playbook
task tepc

# Full test workflow
task tpcf
```

## Configuration

The playbook expects these authentication credentials:
- `pg_k8s`: PostgreSQL database connection (for cluster-based testing)
- `gcs_hmac_local`: GCS HMAC credentials (not used in this test, but required for registration)

Workload parameters:
- `users`: List of users with profile data (name, age, department, years_experience, performance_rating)
- Sub-playbook receives: `user_data` (individual user) and `execution_context` (execution ID)

## Expected Results

### Score Calculation Formula
```
Total Score = (Experience × 0.4) + (Performance × 0.35) + (Department × 0.15) + (Age × 0.1)
```

### Sample Expected Outputs
- **Alice**: ~65-75 points → Senior/Mid-Level
- **Bob**: ~55-65 points → Mid-Level  
- **Charlie**: ~60-70 points → Mid-Level
- **Diana**: ~75-85 points → Executive

### Validation Success Criteria
- All 4 users processed successfully
- All scores within 0-100 range
- All categories from valid set
- PostgreSQL table contains 4 rows
- Validation step reports `all_valid: true`

## Learning Objectives

This test demonstrates:
1. **Playbook Composition**: How to structure parent-child playbook relationships
2. **Iterator Data Flow**: Passing different data to each sub-playbook call
3. **Result Aggregation**: Collecting and validating results from multiple iterations
4. **Complex Business Logic**: Multi-step calculations with workbook actions
5. **Database Integration**: Storing per-iteration results with proper schema
6. **Error Handling**: Robust validation of sub-playbook outputs
7. **Debugging**: Clear logging and result inspection techniques