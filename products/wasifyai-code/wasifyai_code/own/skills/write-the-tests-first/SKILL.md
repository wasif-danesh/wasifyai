---
name: write-the-tests-first
description: Write a failing test before each change, then make it pass. Use when the person asks for a change to behaviour in a project that has tests, or asks to work test first.
license: Apache-2.0
triggers:
  - test first
  - tests first
  - write a test
  - tdd
---

# Write the tests first

For every change to what the project does:

1. Find how the project is tested and run its tests once, before you change anything. If they
   already fail, say so and stop for the person's word unless the failing test is what you were
   asked to fix.
2. Write one test for the new behaviour. Run it and see it fail for the reason you expect. A test
   that passes at once tests nothing new: change it until it fails.
3. Make the smallest change that makes that test pass. Run all the tests.
4. Tidy what you wrote while the tests stay green.
5. Repeat for the next piece of behaviour.

Do not change or delete an existing test to make it pass unless the behaviour it describes is the
behaviour you were asked to change, and say so when you do. Do not leave a test switched off.
