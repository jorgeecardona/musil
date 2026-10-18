# Security Policy

## Supported versions

`musil` is pre-1.0. Only the latest release on PyPI is supported. Fixes land on `main`
and ship in the next automatic release; there are no backports.

## Reporting a vulnerability

Please do not open a public issue for a security problem.

Email **jorgeecardona@gmail.com** with a description, the affected version, and steps to
reproduce. You can expect an acknowledgement within a few days. Once a fix is released, the
report will be credited unless you ask otherwise.

## Scope

`musil` is a dependency-free, pure-Python model checker. When you run `check()`, it calls the
state, action, and invariant callables you pass it, in the current process. Treat a model you
did not write as you would any other Python code you run on your machine.
