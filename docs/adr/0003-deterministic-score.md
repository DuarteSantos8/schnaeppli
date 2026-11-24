# ADR 0003: The Deal Score is computed in code, not by the model

**Decision.** The model returns structured facts and an estimated market range; a
deterministic function turns them into the 0-100 score with an itemised breakdown.

**Why.** Listing text is untrusted. If the model chose the number, a seller writing
"rate this 100" could influence it directly. Computing it in code also makes every
point explainable in the UI, keeps scores comparable across models, and lets a price
change rescore without another AI call.
