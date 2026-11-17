# Chapter 13: Human-in-the-Loop

> From *Agentic Design Patterns — A Hands-On Guide to Building Intelligent Systems* by Antonio Gulli.
> Source: [`docs/Agentic_Design_Patterns.pdf`](../Agentic_Design_Patterns.pdf) (extracted 2026-04-23 via `pdftotext -layout`).
> Overview: [`docs/gulli-book-overview.md`](../gulli-book-overview.md).
> Our platform's status on this pattern: see [`wiki/patterns/`](../../wiki/patterns/).

---

Recovery: This stage is about restoring the agent or system to a stable and
operational state after an error. It could involve reversing recent changes or
transactions to undo the effects of the error (state rollback). A thorough investigation
into the cause of the error is vital for preventing recurrence. Adjusting the agent's
plan, logic, or parameters through a self-correction mechanism or replanning process
may be needed to avoid the same error in the future. In complex or severe cases,
delegating the issue to a human operator or a higher-level system (escalation) might
be the best course of action.

Implementation of this robust exception handling and recovery pattern can transform
AI agents from fragile and unreliable systems into robust, dependable components
capable of operating effectively and resiliently in challenging and highly unpredictable
environments. This ensures that the agents maintain functionality, minimize downtime,
and provide a seamless and reliable experience even when faced with unexpected
issues.


Practical Applications & Use Cases
Exception Handling and Recovery is critical for any agent deployed in a real-world
scenario where perfect conditions cannot be guaranteed.
●​ Customer Service Chatbots: If a chatbot tries to access a customer database
   and the database is temporarily down, it shouldn't crash. Instead, it should detect
   the API error, inform the user about the temporary issue, perhaps suggest trying
   again later, or escalate the query to a human agent.
●​ Automated Financial Trading: A trading bot attempting to execute a trade might
   encounter an "insufficient funds" error or a "market closed" error. It needs to
   handle these exceptions by logging the error, not repeatedly trying the same
   invalid trade, and potentially notifying the user or adjusting its strategy.
●​ Smart Home Automation: An agent controlling smart lights might fail to turn on
   a light due to a network issue or a device malfunction. It should detect this failure,
   perhaps retry, and if still unsuccessful, notify the user that the light could not be
   turned on and suggest manual intervention.
●​ Data Processing Agents: An agent tasked with processing a batch of documents
   might encounter a corrupted file. It should skip the corrupted file, log the error,
   continue processing other files, and report the skipped files at the end rather
   than halting the entire process.

                                                                                       3

 ●​ Web Scraping Agents: When a web scraping agent encounters a CAPTCHA, a
    changed website structure, or a server error (e.g., 404 Not Found, 503 Service
    Unavailable), it needs to handle these gracefully. This could involve pausing, using
    a proxy, or reporting the specific URL that failed.
 ●​ Robotics and Manufacturing: A robotic arm performing an assembly task might
    fail to pick up a component due to misalignment. It needs to detect this failure
    (e.g., via sensor feedback), attempt to readjust, retry the pickup, and if persistent,
    alert a human operator or switch to a different component.
In short, this pattern is fundamental for building agents that are not only intelligent but
also reliable, resilient, and user-friendly in the face of real-world complexities.


Hands-On Code Example (ADK)
Exception handling and recovery are vital for system robustness and reliability.
Consider, for instance, an agent's response to a failed tool call. Such failures can stem
from incorrect tool input or issues with an external service that the tool depends on.

 from google.adk.agents import Agent, SequentialAgent

 # Agent 1: Tries the primary tool. Its focus is narrow and clear.
 primary_handler = Agent(
    name="primary_handler",
    model="gemini-2.0-flash-exp",
    instruction="""
 Your job is to get precise location information.
 Use the get_precise_location_info tool with the user's provided
 address.
    """,
    tools=[get_precise_location_info]
 )

 # Agent 2: Acts as the fallback handler, checking state to decide its
 action.
 fallback_handler = Agent(
    name="fallback_handler",
    model="gemini-2.0-flash-exp",
    instruction="""
 Check if the primary location lookup failed by looking at
 state["primary_location_failed"].
 - If it is True, extract the city from the user's original query and
 use the get_general_area_info tool.
 - If it is False, do nothing.
    """,

                                                                                         4

     tools=[get_general_area_info]
 )

 # Agent 3: Presents the final result from the state.
 response_agent = Agent(
    name="response_agent",
    model="gemini-2.0-flash-exp",
    instruction="""
 Review the location information stored in state["location_result"].
 Present this information clearly and concisely to the user.
 If state["location_result"] does not exist or is empty, apologize
 that you could not retrieve the location.
    """,
    tools=[] # This agent only reasons over the final state.
 )

 # The SequentialAgent ensures the handlers run in a guaranteed order.
 robust_location_agent = SequentialAgent(
    name="robust_location_agent",
    sub_agents=[primary_handler, fallback_handler, response_agent]
 )



This code defines a robust location retrieval system using a ADK's SequentialAgent
with three sub-agents. The primary_handler is the first agent, attempting to get
precise location information using the get_precise_location_info tool. The
fallback_handler acts as a backup, checking if the primary lookup failed by inspecting
a state variable. If the primary lookup failed, the fallback agent extracts the city from
the user's query and uses the get_general_area_info tool. The response_agent is the
final agent in the sequence. It reviews the location information stored in the state. This
agent is designed to present the final result to the user. If no location information was
found, it apologizes. The SequentialAgent ensures that these three agents execute in
a predefined order. This structure allows for a layered approach to location
information retrieval.


At a Glance
What: AI agents operating in real-world environments inevitably encounter
unforeseen situations, errors, and system malfunctions. These disruptions can range
from tool failures and network issues to invalid data, threatening the agent's ability to
complete its tasks. Without a structured way to manage these problems, agents can
be fragile, unreliable, and prone to complete failure when faced with unexpected

                                                                                            5

hurdles. This unreliability makes it difficult to deploy them in critical or complex
applications where consistent performance is essential.

Why: The Exception Handling and Recovery pattern provides a standardized solution
for building robust and resilient AI agents. It equips them with the agentic capability to
anticipate, manage, and recover from operational failures. The pattern involves
proactive error detection, such as monitoring tool outputs and API responses, and
reactive handling strategies like logging for diagnostics, retrying transient failures, or
using fallback mechanisms. For more severe issues, it defines recovery protocols,
including reverting to a stable state, self-correction by adjusting its plan, or escalating
the problem to a human operator. This systematic approach ensures agents can
maintain operational integrity, learn from failures, and function dependably in
unpredictable settings.

Rule of thumb: Use this pattern for any AI agent deployed in a dynamic, real-world
environment where system failures, tool errors, network issues, or unpredictable
inputs are possible and operational reliability is a key requirement.

Visual summary




                                                                                         6

                          Fig.2: Exception handling pattern


Key Takeaways
Essential points to remember:

●​ Exception Handling and Recovery is essential for building robust and reliable
   Agents.
●​ This pattern involves detecting errors, handling them gracefully, and implementing
   strategies to recover.
●​ Error detection can involve validating tool outputs, checking API error codes, and
   using timeouts.
●​ Handling strategies include logging, retries, fallbacks, graceful degradation, and
   notifications.
●​ Recovery focuses on restoring stable operation through diagnosis,
   self-correction, or escalation.
●​ This pattern ensures agents can operate effectively even in unpredictable
   real-world environments.

                                                                                   7

Conclusion
This chapter explores the Exception Handling and Recovery pattern, which is essential
for developing robust and dependable AI agents. This pattern addresses how AI
agents can identify and manage unexpected issues, implement appropriate
responses, and recover to a stable operational state. The chapter discusses various
aspects of this pattern, including the detection of errors, the handling of these errors
through mechanisms such as logging, retries, and fallbacks, and the strategies used
to restore the agent or system to proper function. Practical applications of the
Exception Handling and Recovery pattern are illustrated across several domains to
demonstrate its relevance in handling real-world complexities and potential failures.
These applications show how equipping AI agents with exception handling capabilities
contributes to their reliability and adaptability in dynamic environments.


References
1.​ McConnell, S. (2004). Code Complete (2nd ed.). Microsoft Press.
2.​ Shi, Y., Pei, H., Feng, L., Zhang, Y., & Yao, D. (2024). Towards Fault Tolerance in
    Multi-Agent Reinforcement Learning. arXiv preprint arXiv:2412.00534.
3.​ O'Neill, V. (2022). Improving Fault Tolerance and Reliability of Heterogeneous
    Multi-Agent IoT Systems Using Intelligence Transfer. Electronics, 11(17), 2724.




                                                                                          8

Chapter 13: Human-in-the-Loop
The Human-in-the-Loop (HITL) pattern represents a pivotal strategy in the
development and deployment of Agents. It deliberately interweaves the unique
strengths of human cognition—such as judgment, creativity, and nuanced
understanding—with the computational power and efficiency of AI. This strategic
integration is not merely an option but often a necessity, especially as AI systems
become increasingly embedded in critical decision-making processes.

The core principle of HITL is to ensure that AI operates within ethical boundaries,
adheres to safety protocols, and achieves its objectives with optimal effectiveness.
These concerns are particularly acute in domains characterized by complexity,
ambiguity, or significant risk, where the implications of AI errors or misinterpretations
can be substantial. In such scenarios, full autonomy—where AI systems function
independently without any human intervention—may prove to be imprudent. HITL
acknowledges this reality and emphasizes that even with rapidly advancing AI
technologies, human oversight, strategic input, and collaborative interactions remain
indispensable.

The HITL approach fundamentally revolves around the idea of synergy between
artificial and human intelligence. Rather than viewing AI as a replacement for human
workers, HITL positions AI as a tool that augments and enhances human capabilities.
This augmentation can take various forms, from automating routine tasks to providing
data-driven insights that inform human decisions. The end goal is to create a
collaborative ecosystem where both humans and AI Agents can leverage their distinct
strengths to achieve outcomes that neither could accomplish alone.

In practice, HITL can be implemented in diverse ways. One common approach involves
humans acting as validators or reviewers, examining AI outputs to ensure accuracy
and identify potential errors. Another implementation involves humans actively guiding
AI behavior, providing feedback or making corrections in real-time. In more complex
setups, humans may collaborate with AI as partners, jointly solving problems or
making decisions through interactive dialog or shared interfaces. Regardless of the
specific implementation, the HITL pattern underscores the importance of maintaining
human control and oversight, ensuring that AI systems remain aligned with human
ethics, values, goals, and societal expectations.




                                                                                            1

Human-in-the-Loop Pattern Overview
The Human-in-the-Loop (HITL) pattern integrates artificial intelligence with human
input to enhance Agent capabilities. This approach acknowledges that optimal AI
performance frequently requires a combination of automated processing and human
insight, especially in scenarios with high complexity or ethical considerations. Rather
than replacing human input, HITL aims to augment human abilities by ensuring that
critical judgments and decisions are informed by human understanding.

HITL encompasses several key aspects: Human Oversight, which involves monitoring
AI agent performance and output (e.g., via log reviews or real-time dashboards) to
ensure adherence to guidelines and prevent undesirable outcomes. Intervention and
Correction occurs when an AI agent encounters errors or ambiguous scenarios and
may request human intervention; human operators can rectify errors, supply missing
data, or guide the agent, which also informs future agent improvements. Human
Feedback for Learning is collected and used to refine AI models, prominently in
methodologies like reinforcement learning with human feedback, where human
preferences directly influence the agent's learning trajectory. Decision Augmentation
is where an AI agent provides analyses and recommendations to a human, who then
makes the final decision, enhancing human decision-making through AI-generated
insights rather than full autonomy. Human-Agent Collaboration is a cooperative
interaction where humans and AI agents contribute their respective strengths; routine
data processing may be handled by the agent, while creative problem-solving or
complex negotiations are managed by the human. Finally, Escalation Policies are
established protocols that dictate when and how an agent should escalate tasks to
human operators, preventing errors in situations beyond the agent's capability.
Implementing HITL patterns enables the use of Agents in sensitive sectors where full
autonomy is not feasible or permitted. It also provides a mechanism for ongoing
improvement through feedback loops. For example, in finance, the final approval of a
large corporate loan requires a human loan officer to assess qualitative factors like
leadership character. Similarly, in the legal field, core principles of justice and
accountability demand that a human judge retain final authority over critical decisions
like sentencing, which involve complex moral reasoning.

Caveats: Despite its benefits, the HITL pattern has significant caveats, chief among
them being a lack of scalability. While human oversight provides high accuracy,
operators cannot manage millions of tasks, creating a fundamental trade-off that
often requires a hybrid approach combining automation for scale and HITL for

                                                                                          2

accuracy. Furthermore, the effectiveness of this pattern is heavily dependent on the
expertise of the human operators; for example, while an AI can generate software
code, only a skilled developer can accurately identify subtle errors and provide the
correct guidance to fix them. This need for expertise also applies when using HITL to
generate training data, as human annotators may require special training to learn how
to correct an AI in a way that produces high-quality data. Lastly, implementing HITL
raises significant privacy concerns, as sensitive information must often be rigorously
anonymized before it can be exposed to a human operator, adding another layer of
process complexity.


Practical Applications & Use Cases
The Human-in-the-Loop pattern is vital across a wide range of industries and
applications, particularly where accuracy, safety, ethics, or nuanced understanding
are paramount.
●​ Content Moderation: AI agents can rapidly filter vast amounts of online content
   for violations (e.g., hate speech, spam). However, ambiguous cases or borderline
   content are escalated to human moderators for review and final decision,
   ensuring nuanced judgment and adherence to complex policies.
●​ Autonomous Driving: While self-driving cars handle most driving tasks
   autonomously, they are designed to hand over control to a human driver in
   complex, unpredictable, or dangerous situations that the AI cannot confidently
   navigate (e.g., extreme weather, unusual road conditions).
●​ Financial Fraud Detection: AI systems can flag suspicious transactions based on
   patterns. However, high-risk or ambiguous alerts are often sent to human analysts
   who investigate further, contact customers, and make the final determination on
   whether a transaction is fraudulent.
●​ Legal Document Review: AI can quickly scan and categorize thousands of legal
   documents to identify relevant clauses or evidence. Human legal professionals
   then review the AI's findings for accuracy, context, and legal implications,
   especially for critical cases.
●​ Customer Support (Complex Queries): A chatbot might handle routine
   customer inquiries. If the user's problem is too complex, emotionally charged, or
   requires empathy that the AI cannot provide, the conversation is seamlessly
   handed over to a human support agent.
●​ Data Labeling and Annotation: AI models often require large datasets of labeled
   data for training. Humans are put in the loop to accurately label images, text, or



                                                                                      3

   audio, providing the ground truth that the AI learns from. This is a continuous
   process as models evolve.
●​ Generative AI Refinement: When an LLM generates creative content (e.g.,
   marketing copy, design ideas), human editors or designers review and refine the
   output, ensuring it meets brand guidelines, resonates with the target audience,
   and maintains quality.
●​ Autonomous Networks: AI systems are capable of analyzing alerts and
   forecasting network issues and traffic anomalies by leveraging key performance
   indicators (KPIs) and identified patterns. Nevertheless, crucial decisions—such as
   addressing high-risk alerts—are frequently escalated to human analysts. These
   analysts conduct further investigation and make the ultimate determination
   regarding the approval of network changes.
This pattern exemplifies a practical method for AI implementation. It harnesses AI for
enhanced scalability and efficiency, while maintaining human oversight to ensure
quality, safety, and ethical compliance.


"Human-on-the-loop" is a variation of this pattern where human experts define the
overarching policy, and the AI then handles immediate actions to ensure compliance.
Let's consider two examples:

●​ Automated financial trading system: In this scenario, a human financial expert
   sets the overarching investment strategy and rules. For instance, the human
