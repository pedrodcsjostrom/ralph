# Agents run at project scope only

A headless agent normally inherits the runner's personal settings, instructions, memory and installed skills, which means the same spec runs under different instructions on different machines without anyone seeing the difference.
Ralph launches its agents with those user-level sources switched off, so an agent sees only what the project has checked in, the bundled skills and the project rules; authentication still comes from the runner's login.
This deliberately gives up the convenience of a maintainer's own memory reaching the agents: anything an unattended agent needs to know has to be written into the project, where it is reviewed and versioned.
