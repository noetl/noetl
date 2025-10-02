# Iterator Step Feature Documentation

## Overview
The iterator step (`type: iterator`) allows a step to be repeated automatically for a given list of items.

Instead of running the step only once, the loop makes the step process each item independently at the same time, then collects all results into a single output list.

This feature is especially powerful when used with a nested **playbook** or other task as the iterator's `task`. The nested task is executed for each element.

---

## How It Works
Note: Aggregated results are produced only for iterator steps. Non-iterator steps never receive an automatic aggregated result.
1. You provide an array of input items.
   Example: `[{"name": "Anna", "age": 30}, {"name": "Bob", "age": 25}, {"name": "Charlie", "age": 18}]`

2. The nested task (or playbook) is applied to each item in the list, one at a time.
   Example: A playbook called **"Increase Age"** will process each user and add 1 to their age.

3. The results of each processed item are collected into a new array.
   Example: `[{"name": "Anna", "age": 31}, {"name": "Bob", "age": 26}, {"name": "Charlie", "age": 18}]`

---

## Benefits
- **Efficiency:** One definition of a step or playbook can handle multiple items automatically.  
- **Scalability:** Ideal for workflows that deal with batches of data, documents, or requests.  
- **Flexibility:** Can be applied to both individual steps and entire playbooks.

---

## Visualization

### Picture 1: Normal Step (without loop)
![Simple Playbook Step](images/Simple%20Playbook%20Step.png)
- **Caption:** "A step processes only one item at a time."

---

### Picture 2: Iterator Step
![Looped Playbook Step](images/Looped%20Playbook%20Step.png)
- **Caption:** "With the loop enabled, a given array of items will be transformed by applying the step (in this case, the playbook) to each item. The result is an array of outputs, each corresponding to the processed input item."

---

### Picture 3: Workflow Graph with Iterator Step
![Looped Playbook Step Detailed](images/Looped%20Playbook%20Step%20Detailed.png)
- **Caption:** "This whole process can be described as the simultaneous execution of several steps of the same type (here, playbooks) for each item in the input array. The results are then combined into one output array of transformed items."

---
