# Chapter 12: Exception Handling and Recovery

> From *Agentic Design Patterns — A Hands-On Guide to Building Intelligent Systems* by Antonio Gulli.
> Source: [`docs/Agentic_Design_Patterns.pdf`](../Agentic_Design_Patterns.pdf) (extracted 2026-04-23 via `pdftotext -layout`).
> Overview: [`docs/gulli-book-overview.md`](../gulli-book-overview.md).
> Our platform's status on this pattern: see [`wiki/patterns/`](../../wiki/patterns/).

---


   # Example 2
   # use_case_input = "Write code to count the number of files in

                                                                      7

current directory and all its nested sub directories, and print the
total count"
   # goals_input = (
   #     "Code simple to understand, Functionally correct, Handles
comprehensive edge cases, Ignore recommendations for performance,
Ignore recommendations for test suite use like unittest or pytest"
   # )
   # run_code_agent(use_case_input, goals_input)

   # Example 3
   # use_case_input = "Write code which takes a command line input
of a word doc or docx file and opens it and counts the number of
words, and characters in it and prints all"
   # goals_input = "Code simple to understand, Functionally
correct, Handles edge cases"
   # run_code_agent(use_case_input, goals_input)



Along with this brief, you provide a strict quality checklist, which represents the
objectives the final code must meet—criteria like "the solution must be simple," "it
must be functionally correct," or "it needs to handle unexpected edge cases."




                                                                                       8

                         Fig.1: Goal Setting and Monitor example

With this assignment in hand, the AI programmer gets to work and produces its first
draft of the code. However, instead of immediately submitting this initial version, it
pauses to perform a crucial step: a rigorous self-review. It meticulously compares its
own creation against every item on the quality checklist you provided, acting as its
own quality assurance inspector. After this inspection, it renders a simple, unbiased
verdict on its own progress: "True" if the work meets all standards, or "False" if it falls
short.

If the verdict is "False," the AI doesn't give up. It enters a thoughtful revision phase,
using the insights from its self-critique to pinpoint the weaknesses and intelligently
rewrite the code. This cycle of drafting, self-reviewing, and refining continues, with
each iteration aiming to get closer to the goals. This process repeats until the AI finally
achieves a "True" status by satisfying every requirement, or until it reaches a
predefined limit of attempts, much like a developer working against a deadline. Once




                                                                                              9

the code passes this final inspection, the script packages the polished solution,
adding helpful comments and saving it to a clean, new Python file, ready for use.

Caveats and Considerations: It is important to note that this is an exemplary
illustration and not production-ready code. For real-world applications, several factors
must be taken into account. An LLM may not fully grasp the intended meaning of a
goal and might incorrectly assess its performance as successful. Even if the goal is
well understood, the model may hallucinate. When the same LLM is responsible for
both writing the code and judging its quality, it may have a harder time discovering it
is going in the wrong direction.

Ultimately, LLMs do not produce flawless code by magic; you still need to run and test
the produced code. Furthermore, the "monitoring" in the simple example is basic and
creates a potential risk of the process running forever.

Act as an expert code reviewer with a deep commitment to producing
clean, correct, and simple code. Your core mission is to eliminate
code "hallucinations" by ensuring every suggestion is grounded in
reality and best practices.
When I provide you with a code snippet, I want you to:

-- Identify and Correct Errors: Point out any logical flaws, bugs, or
potential runtime errors.

-- Simplify and Refactor: Suggest changes that make the code more
readable, efficient, and maintainable without sacrificing
correctness.

-- Provide Clear Explanations: For every suggested change, explain
why it is an improvement, referencing principles of clean code,
performance, or security.

-- Offer Corrected Code: Show the "before" and "after" of your
suggested changes so the improvement is clear.

Your feedback should be direct, constructive, and always aimed at
improving the quality of the code.



A more robust approach involves separating these concerns by giving specific roles to
a crew of agents. For instance, I have built a personal crew of AI agents using Gemini
where each has a specific role:


                                                                                     10

   ●​ The Peer Programmer: Helps write and brainstorm code.
   ●​ The Code Reviewer: Catches errors and suggests improvements.
   ●​ The Documenter: Generates clear and concise documentation.
   ●​ The Test Writer: Creates comprehensive unit tests.
   ●​ The Prompt Refiner: Optimizes interactions with the AI.

In this multi-agent system, the Code Reviewer, acting as a separate entity from the
programmer agent, has a prompt similar to the judge in the example, which
significantly improves objective evaluation. This structure naturally leads to better
practices, as the Test Writer agent can fulfill the need to write unit tests for the code
produced by the Peer Programmer.

I leave to the interested reader the task of adding these more sophisticated controls
and making the code closer to production-ready.


At a Glance
What: AI agents often lack a clear direction, preventing them from acting with
purpose beyond simple, reactive tasks. Without defined objectives, they cannot
independently tackle complex, multi-step problems or orchestrate sophisticated
workflows. Furthermore, there is no inherent mechanism for them to determine if their
actions are leading to a successful outcome. This limits their autonomy and prevents
them from being truly effective in dynamic, real-world scenarios where mere task
execution is insufficient.

Why: The Goal Setting and Monitoring pattern provides a standardized solution by
embedding a sense of purpose and self-assessment into agentic systems. It involves
explicitly defining clear, measurable objectives for the agent to achieve. Concurrently,
it establishes a monitoring mechanism that continuously tracks the agent's progress
and the state of its environment against these goals. This creates a crucial feedback
loop, enabling the agent to assess its performance, correct its course, and adapt its
plan if it deviates from the path to success. By implementing this pattern, developers
can transform simple reactive agents into proactive, goal-oriented systems capable of
autonomous and reliable operation.

Rule of thumb: Use this pattern when an AI agent must autonomously execute a
multi-step task, adapt to dynamic conditions, and reliably achieve a specific,
high-level objective without constant human intervention.



                                                                                        11

Visual summary:




                             Fig.2: Goal design patterns


Key takeaways
Key takeaways include:

●​ Goal Setting and Monitoring equips agents with purpose and mechanisms to
   track progress.
●​ Goals should be specific, measurable, achievable, relevant, and time-bound
   (SMART).
●​ Clearly defining metrics and success criteria is essential for effective monitoring.
●​ Monitoring involves observing agent actions, environmental states, and tool
   outputs.
●​ Feedback loops from monitoring allow agents to adapt, revise plans, or escalate
   issues.
●​ In Google's ADK, goals are often conveyed through agent instructions, with

                                                                                      12

    monitoring accomplished through state management and tool interactions.


Conclusion
This chapter focused on the crucial paradigm of Goal Setting and Monitoring. I
highlighted how this concept transforms AI agents from merely reactive systems into
proactive, goal-driven entities. The text emphasized the importance of defining clear,
measurable objectives and establishing rigorous monitoring procedures to track
progress. Practical applications demonstrated how this paradigm supports reliable
autonomous operation across various domains, including customer service and
robotics. A conceptual coding example illustrates the implementation of these
principles within a structured framework, using agent directives and state
management to guide and evaluate an agent's achievement of its specified goals.
Ultimately, equipping agents with the ability to formulate and oversee goals is a
fundamental step toward building truly intelligent and accountable AI systems.


References
1.​ SMART Goals Framework. https://en.wikipedia.org/wiki/SMART_criteria




                                                                                     13

Chapter 12: Exception Handling and
Recovery
For AI agents to operate reliably in diverse real-world environments, they must be able
to manage unforeseen situations, errors, and malfunctions. Just as humans adapt to
unexpected obstacles, intelligent agents need robust systems to detect problems,
initiate recovery procedures, or at least ensure controlled failure. This essential
requirement forms the basis of the Exception Handling and Recovery pattern.

This pattern focuses on developing exceptionally durable and resilient agents that can
maintain uninterrupted functionality and operational integrity despite various
difficulties and anomalies. It emphasizes the importance of both proactive preparation
and reactive strategies to ensure continuous operation, even when facing challenges.
This adaptability is critical for agents to function successfully in complex and
unpredictable settings, ultimately boosting their overall effectiveness and
trustworthiness.

The capacity to handle unexpected events ensures these AI systems are not only
intelligent but also stable and reliable, which fosters greater confidence in their
deployment and performance. Integrating comprehensive monitoring and diagnostic
tools further strengthens an agent's ability to quickly identify and address issues,
preventing potential disruptions and ensuring smoother operation in evolving
conditions. These advanced systems are crucial for maintaining the integrity and
efficiency of AI operations, reinforcing their ability to manage complexity and
unpredictability.

This pattern may sometimes be used with reflection. For example, if an initial attempt
fails and raises an exception, a reflective process can analyze the failure and
reattempt the task with a refined approach, such as an improved prompt, to resolve
the error.


Exception Handling and Recovery Pattern Overview
The Exception Handling and Recovery pattern addresses the need for AI agents to
manage operational failures. This pattern involves anticipating potential issues, such
as tool errors or service unavailability, and developing strategies to mitigate them.
These strategies may include error logging, retries, fallbacks, graceful degradation,

                                                                                         1

and notifications. Additionally, the pattern emphasizes recovery mechanisms like state
rollback, diagnosis, self-correction, and escalation, to restore agents to stable
operation. Implementing this pattern enhances the reliability and robustness of AI
agents, allowing them to function in unpredictable environments. Examples of
practical applications include chatbots managing database errors, trading bots
handling financial errors, and smart home agents addressing device malfunctions. The
pattern ensures that agents can continue to operate effectively despite encountering
complexities and failures.




       Fig.1: Key components of exception handling and recovery for AI agents

Error Detection: This involves meticulously identifying operational issues as they
arise. This could manifest as invalid or malformed tool outputs, specific API errors
such as 404 (Not Found) or 500 (Internal Server Error) codes, unusually long
response times from services or APIs, or incoherent and nonsensical responses that
deviate from expected formats. Additionally, monitoring by other agents or specialized
monitoring systems might be implemented for more proactive anomaly detection,
enabling the system to catch potential issues before they escalate.

Error Handling: Once an error is detected, a carefully thought-out response plan is
essential. This includes recording error details meticulously in logs for later debugging
and analysis (logging). Retrying the action or request, sometimes with slightly
adjusted parameters, may be a viable strategy, especially for transient errors (retries).
Utilizing alternative strategies or methods (fallbacks) can ensure that some
functionality is maintained. Where complete recovery is not immediately possible, the
agent can maintain partial functionality to provide at least some value (graceful

                                                                                        2

degradation). Finally, alerting human operators or other agents might be crucial for
situations that require human intervention or collaboration (notification).

