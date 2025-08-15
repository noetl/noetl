# Cryptography Problem

## Overview
Grover’s Algorithm is a quantum search algorithm that finds a marked item in an unsorted database in **O(√N)** time, providing a quadratic speedup over classical search.  
This example demonstrates how to implement Grover’s Algorithm using the Qiskit SDK to solve a search problem similar to the one explained in the 3Blue1Brown video *"But what is quantum computing? (Grover's Algorithm)"*.
[https://www.youtube.com/watch?v=RQWpF2Gb-gU]  


The algorithm works by:
1. **Creating superposition** over all possible states.
2. **Applying an oracle** that flips the phase of the target state.
3. **Applying a diffusion operator** that amplifies the probability of the target state.
4. **Repeating steps 2 and 3** an optimal number of times, then measuring to find the solution.

---

## Playbook Details
*(To be filled in later)*

---

## Purpose
The purpose of this playbook is to:
- Provide a clear and reproducible example of Grover’s Algorithm in Qiskit.
- Help learners bridge theory with hands-on quantum programming.
- Serve as a reference for building more complex quantum search applications.