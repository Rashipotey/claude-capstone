"""CLI / Orchestrator stage. Parses arguments, sequences the stages, maps outcomes to exit codes.

Implemented in plan tasks T09 (argument handling) and T15 (sequencing). This module
holds no analysis, mapping, generation, or validation logic. It is the only module
allowed to import the other stage modules, and only their public functions.
"""

__all__ = []
