-- Demo data. Standard codes follow the Common Core (CCSS) and CSTA numbering; descriptions are paraphrased.
-- Passages, items and students are original and fictional.
INSERT INTO standards (code, subject, grade, title, description) VALUES
 ('CCSS.MATH.6.RP.A.1', 'MATH', 6, 'Ratio language',
  'Understand the concept of a ratio and use ratio language to describe a relationship between two quantities, for example "for every 2 wings there is 1 beak".'),
 ('CCSS.MATH.6.RP.A.3', 'MATH', 6, 'Ratio and rate reasoning',
  'Use ratio and rate reasoning to solve real-world and mathematical problems, using tables of equivalent ratios, tape diagrams, double number lines, unit rates and percents.'),
 ('CCSS.MATH.7.RP.A.2', 'MATH', 7, 'Proportional relationships',
  'Recognize and represent proportional relationships between quantities: test for equivalent ratios in a table or graph, identify the constant of proportionality, and write equations such as y = kx.'),
 ('CCSS.ELA-LITERACY.RI.6.1', 'ELA', 6, 'Cite textual evidence',
  'Cite evidence from an informational text to support an analysis of what the text says explicitly and the inferences drawn from it.'),
 ('CCSS.ELA-LITERACY.RI.6.2', 'ELA', 6, 'Central idea',
  'Determine the central idea of an informational text and how it is developed through particular details; give a summary that is free of personal opinions or judgments.'),
 ('CSTA.2-AP-12', 'CS', 7, 'Control structures',
  'Design and iteratively develop programs that combine control structures, including loops and conditionals, to solve a problem.'),
 ('CSTA.2-AP-13', 'CS', 7, 'Decomposition',
  'Break a problem into smaller parts and write functions for each part to make a program easier to design, build and test.')
ON CONFLICT DO NOTHING;

INSERT INTO students (id, name, grade) VALUES ('STU-MAYA', 'Maya', 6), ('STU-LEO', 'Leo', 7), ('STU-EVAL', 'Eval Student', 6)
ON CONFLICT DO NOTHING;

-- Knowledge base: standards plus two short original passages.
INSERT INTO knowledge_chunks (source_type, source_id, content)
SELECT 'STANDARD', code, title || ' (' || code || ', grade ' || grade || ' ' || subject || '): ' || description FROM standards
ON CONFLICT DO NOTHING;
INSERT INTO knowledge_chunks (source_type, source_id, content) VALUES
 ('PASSAGE', 'P-ROOFTOP-BEES', 'Bees on the Rooftops. In many cities, flat rooftops sit empty. A growing number of building owners now use them for beehives and small gardens. City bees have plenty to eat, because parks, street trees and window boxes bloom at different times through the spring and summer. Rooftop gardens also cool the buildings below them, which lowers energy bills on hot days. Some schools keep hives on their roofs so students can study how bees pollinate plants. Beekeepers say the honey from city hives tastes different from block to block, because the bees visit different flowers. Rooftop hives are not a solution to every problem bees face, but they show how unused spaces can support nature in crowded places.'),
 ('PASSAGE', 'P-RIVER-CLEANUP', 'The River Cleanup. Every April, volunteers in the town of Millbrook spend a Saturday pulling trash from the Willow River. Ten years ago, the first cleanup collected more than two tons of bottles, tires and plastic bags. Since then, the town added recycling bins near the riverbank and fined businesses that dumped waste. Last year, volunteers collected only four hundred pounds of trash, and fishermen reported seeing trout again for the first time in decades. Organizers say the cleanup works because people who help one Saturday a year start noticing litter every other day too.')
ON CONFLICT DO NOTHING;

INSERT INTO items (id, standard_code, item_type, difficulty, stem, choices, answer_key, rubric, tests, status, source) VALUES
 ('11111111-0000-4000-8000-000000000001', 'CCSS.MATH.6.RP.A.3', 'MULTIPLE_CHOICE', 'EASY',
  'A store sells 12 granola bars for $9. At the same rate, how much do 20 granola bars cost?',
  '["$12", "$15", "$18", "$21"]', 'B',
  '[{"criterion": "Correct choice", "max_points": 1, "descriptors": "1 point for B ($15)."}]', NULL, 'APPROVED', 'SEED'),
 ('11111111-0000-4000-8000-000000000002', 'CCSS.MATH.6.RP.A.3', 'CONSTRUCTED_RESPONSE', 'MEDIUM',
  'Maya mixes 3 cups of blue paint with 5 cups of yellow paint to make green paint. She needs 24 cups of green paint in total, mixed in the same ratio. How many cups of blue paint does she need? Explain how you found your answer.',
  NULL, '9 cups of blue paint. The ratio of blue to total paint is 3:8, and 24 is 3 times 8, so blue is 3 x 3 = 9 cups (yellow is 15 cups).',
  '[{"criterion": "Correct answer", "max_points": 1, "descriptors": "1 point for 9 cups of blue paint."},
    {"criterion": "Ratio reasoning", "max_points": 2, "descriptors": "2 points: explains the 3:8 part-to-total ratio and scaling by 3 (or an equivalent table, tape diagram or unit rate). 1 point: some correct ratio reasoning with a gap or error. 0: no ratio reasoning."},
    {"criterion": "Clear communication", "max_points": 1, "descriptors": "1 point: steps are understandable and the answer is labeled with units (cups)."}]',
  NULL, 'APPROVED', 'SEED'),
 ('11111111-0000-4000-8000-000000000003', 'CCSS.ELA-LITERACY.RI.6.2', 'CONSTRUCTED_RESPONSE', 'MEDIUM',
  'Read "Bees on the Rooftops." What is the central idea of the passage? Support your answer with two details from the passage.',
  NULL, 'Central idea: unused city rooftops can be turned into spaces that support nature, such as beehives and gardens. Details: city bees find food from parks, trees and window boxes; rooftop gardens cool buildings; schools use rooftop hives to study pollination.',
  '[{"criterion": "Central idea", "max_points": 2, "descriptors": "2 points: states that rooftops or unused city spaces can support nature/bees. 1 point: a topic (bees, rooftops) without a clear central idea. 0: incorrect or missing."},
    {"criterion": "Supporting details", "max_points": 2, "descriptors": "1 point for each relevant detail from the passage (up to 2). Details must come from the text, not personal opinion."}]',
  NULL, 'APPROVED', 'SEED'),
 ('11111111-0000-4000-8000-000000000004', 'CSTA.2-AP-12', 'CODE', 'MEDIUM',
  'Write a Python function solve(scores) that returns the average of a list of test scores, rounded to 1 decimal place. If the list is empty, return 0.0.',
  NULL, E'def solve(scores):\n    if not scores:\n        return 0.0\n    return round(sum(scores) / len(scores), 1)',
  '[{"criterion": "Passes test cases", "max_points": 4, "descriptors": "1 point for each passing test case."}]',
  '[{"args": [[90, 80, 70]], "expected": 80.0}, {"args": [[]], "expected": 0.0}, {"args": [[85]], "expected": 85.0}, {"args": [[88, 91]], "expected": 89.5}]',
  'APPROVED', 'SEED')
ON CONFLICT DO NOTHING;
