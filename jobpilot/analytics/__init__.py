"""Aggregates for the Market page.

Separate from ``api/routes/stats.py`` because that module already answers two
different questions (the job funnel, and what the model backends cost) and a
third would make it a 500-line file doing three jobs.

Every function here returns its **coverage** alongside its numbers. That is not
decoration. Most facets in this database are sparse — LinkedIn is the largest
source and carries no skills, no salary and often no date — so a bar chart drawn
without saying how many jobs it saw describes the boards that happen to tag
their ads and looks like it describes the market. The rule is the same one
``llm/stats.MIN_SAMPLE`` enforces, applied to a different kind of thinness.
"""
