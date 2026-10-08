# Entailment benchmark fixtures

These five JSON files are fixed labeled inputs required by the offline entailment benchmark builder and its CI tests. They were copied byte for byte from the historical datasets at `4f3f3028a9e9a72c4a091e30f225e14f1d72e3d9`.

The original dataset paths are retained beneath this directory so `SOURCES`, `source_files`, and each row's `source_dataset` preserve their historical identities. The builder reads the fixtures here without depending on the original root experiment directories.

The historical audit-role labels are frozen benchmark inputs, not measurements of current product performance. Their presence does not establish independent human review or a current model-quality result.
