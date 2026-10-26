"""DOCSYNC: propose documentation updates from a local Git diff (v1, Python 3.12, standard library only).

The package has one module per stage plus ``contracts`` for the shared data
contracts. A stage module must not import another stage's internals; only the
``cli`` orchestrator composes the stages, through their public functions.
"""
