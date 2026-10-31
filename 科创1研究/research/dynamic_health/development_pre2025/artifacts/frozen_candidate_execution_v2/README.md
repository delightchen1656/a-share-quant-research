# Frozen candidate execution compliance v2

This package is an execution-compliance repair, not a strategy upgrade. `candidate.json`, `event_model.joblib`, and `stop_risk_model.joblib` are byte-identical to the prior frozen package. Model scores, thresholds, dynamic health rules, and position-sizing fractions are unchanged.

The repaired engine enforces integer shares, a 200-share minimum STAR-market buy with one-share increments thereafter, T+1 selling, suspension and zero-volume blocking, open-limit-up buy blocking, open-limit-down sell blocking, and an all-in affordability check that prevents fees and slippage from producing negative cash.

All reproduction and rule-test evidence in this package uses only the approved `inputs_pre2025` boundary snapshot or synthetic bars embedded in `test_execution_rules.py`.
