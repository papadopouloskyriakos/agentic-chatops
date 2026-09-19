# Chapter 17: Reasoning Techniques

> From *Agentic Design Patterns — A Hands-On Guide to Building Intelligent Systems* by Antonio Gulli.
> Source: [`docs/Agentic_Design_Patterns.pdf`](../Agentic_Design_Patterns.pdf) (extracted 2026-04-23 via `pdftotext -layout`).
> Overview: [`docs/gulli-book-overview.md`](../gulli-book-overview.md).
> Our platform's status on this pattern: see [`wiki/patterns/`](../../wiki/patterns/).

---

print("
print("  🧠Model Used:", result["model"])
          Response:\n", result["response"])



This Python code implements a prompt routing system to answer user questions. It
begins by loading necessary API keys from a .env file for OpenAI and Google Custom
Search. The core functionality lies in classifying the user's prompt into three
categories: simple, reasoning, or internet search. A dedicated function utilizes an
OpenAI model for this classification step. If the prompt requires current information, a
Google search is performed using the Google Custom Search API. Another function

                                                                                       9

then generates the final response, selecting an appropriate OpenAI model based on
the classification. For internet search queries, the search results are provided as
context to the model. The main handle_prompt function orchestrates this workflow,
calling the classification and search (if needed) functions before generating the
response. It returns the classification, the model used, and the generated answer. This
system efficiently directs different types of queries to optimized methods for a better
response.


Hands-On Code Example (OpenRouter)
OpenRouter offers a unified interface to hundreds of AI models via a single API
endpoint. It provides automated failover and cost-optimization, with easy integration
through your preferred SDK or framework.


REDACTED_a7b84d63quests
import json
response = requests.post(
 url="https://openrouter.ai/api/v1/chat/completions",
 headers={
   "Authorization": "Bearer <OPENROUTER_API_KEY>",
   "HTTP-Referer": "<YOUR_SITE_URL>", # Optional. Site URL for
rankings on openrouter.ai.
   "X-Title": "<YOUR_SITE_NAME>", # Optional. Site title for rankings
on openrouter.ai.
 },
 data=json.dumps({
   "model": "openai/gpt-4o", # Optional
   "messages": [
     {
       "role": "user",
       "content": "What is the meaning of life?"
     }
   ]
 })
)


This code snippet uses the requests library to interact with the OpenRouter API. It
sends a POST request to the chat completion endpoint with a user message. The
request includes authorization headers with an API key and optional site information.
The goal is to get a response from a specified language model, in this case,
"openai/gpt-4o".



                                                                                    10

Openrouter offers two distinct methodologies for routing and determining the
computational model used to process a given request.

   ●​ Automated Model Selection: This function routes a request to an optimized
      model chosen from a curated set of available models. The selection is
      predicated on the specific content of the user's prompt. The identifier of the
      model that ultimately processes the request is returned in the response's
      metadata.


{
 "model": "openrouter/auto",
 ... // Other params
}


   ●​ Sequential Model Fallback: This mechanism provides operational redundancy
      by allowing users to specify a hierarchical list of models. The system will first
      attempt to process the request with the primary model designated in the
      sequence. Should this primary model fail to respond due to any number of error
      conditions—such as service unavailability, rate-limiting, or content filtering—the
      system will automatically re-route the request to the next specified model in
      the sequence. This process continues until a model in the list successfully
      executes the request or the list is exhausted. The final cost of the operation
      and the model identifier returned in the response will correspond to the model
      that successfully completed the computation.


{
 "models": ["anthropic/claude-3.5-sonnet", "gryphe/mythomax-l2-13b"],
 ... // Other params
}


OpenRouter offers a detailed leaderboard ( https://openrouter.ai/rankings) which ranks
available AI models based on their cumulative token production. It also offers latest
models from different providers (ChatGPT, Gemini, Claude) (see Fig. 1)




                                                                                       11

                  Fig. 1: OpenRouter Web site (https://openrouter.ai/)


Beyond Dynamic Model Switching: A Spectrum of
Agent Resource Optimizations
Resource-aware optimization is paramount in developing intelligent agent systems
that operate efficiently and effectively within real-world constraints. Let's see a
number of additional techniques:

Dynamic Model Switching is a critical technique involving the strategic selection of
large language models based on the intricacies of the task at hand and the available
computational resources. When faced with simple queries, a lightweight,
cost-effective LLM can be deployed, whereas complex, multifaceted problems
necessitate the utilization of more sophisticated and resource-intensive models.

Adaptive Tool Use & Selection ensures agents can intelligently choose from a suite
of tools, selecting the most appropriate and efficient one for each specific sub-task,
with careful consideration given to factors like API usage costs, latency, and execution
time. This dynamic tool selection enhances overall system efficiency by optimizing the
use of external APIs and services.

Contextual Pruning & Summarization plays a vital role in managing the amount of
information processed by agents, strategically minimizing the prompt token count and
reducing inference costs by intelligently summarizing and selectively retaining only the
                                                                                      12

most relevant information from the interaction history, preventing unnecessary
computational overhead.

Proactive Resource Prediction involves anticipating resource demands by
forecasting future workloads and system requirements, which allows for proactive
allocation and management of resources, ensuring system responsiveness and
preventing bottlenecks.

Cost-Sensitive Exploration in multi-agent systems extends optimization
considerations to encompass communication costs alongside traditional
computational costs, influencing the strategies employed by agents to collaborate
and share information, aiming to minimize the overall resource expenditure.

Energy-Efficient Deployment is specifically tailored for environments with stringent
resource constraints, aiming to minimize the energy footprint of intelligent agent
systems, extending operational time and reducing overall running costs.

Parallelization & Distributed Computing Awareness leverages distributed
resources to enhance the processing power and throughput of agents, distributing
computational workloads across multiple machines or processors to achieve greater
efficiency and faster task completion.

Learned Resource Allocation Policies introduce a learning mechanism, enabling
agents to adapt and optimize their resource allocation strategies over time based on
feedback and performance metrics, improving efficiency through continuous
refinement.

Graceful Degradation and Fallback Mechanisms ensure that intelligent agent
systems can continue to function, albeit perhaps at a reduced capacity, even when
resource constraints are severe, gracefully degrading performance and falling back to
alternative strategies to maintain operation and provide essential functionality.


At a Glance
What: Resource-Aware Optimization addresses the challenge of managing the
consumption of computational, temporal, and financial resources in intelligent
systems. LLM-based applications can be expensive and slow, and selecting the best
model or tool for every task is often inefficient. This creates a fundamental trade-off
between the quality of a system's output and the resources required to produce it.



                                                                                      13

Without a dynamic management strategy, systems cannot adapt to varying task
complexities or operate within budgetary and performance constraints.

Why: The standardized solution is to build an agentic system that intelligently
monitors and allocates resources based on the task at hand. This pattern typically
employs a "Router Agent" to first classify the complexity of an incoming request. The
request is then forwarded to the most suitable LLM or tool—a fast, inexpensive model
for simple queries, and a more powerful one for complex reasoning. A "Critique
Agent" can further refine the process by evaluating the quality of the response,
providing feedback to improve the routing logic over time. This dynamic, multi-agent
approach ensures the system operates efficiently, balancing response quality with
cost-effectiveness.

Rule of thumb: Use this pattern when operating under strict financial budgets for API
calls or computational power, building latency-sensitive applications where quick
response times are critical, deploying agents on resource-constrained hardware such
as edge devices with limited battery life, programmatically balancing the trade-off
between response quality and operational cost, and managing complex, multi-step
workflows where different tasks have varying resource requirements.

Visual Summary




                                                                                   14

              Fig. 2: Resource-Aware Optimization Design Pattern


Key Takeaways
 ●​ Resource-Aware Optimization is Essential: Intelligent agents can manage
    computational, temporal, and financial resources dynamically. Decisions
    regarding model usage and execution paths are made based on real-time
    constraints and objectives.
 ●​ Multi-Agent Architecture for Scalability: Google's ADK provides a multi-agent
    framework, enabling modular design. Different agents (answering, routing,
    critique) handle specific tasks.
 ●​ Dynamic, LLM-Driven Routing: A Router Agent directs queries to language
    models (Gemini Flash for simple, Gemini Pro for complex) based on query
    complexity and budget. This optimizes cost and performance.
 ●​ Critique Agent Functionality: A dedicated Critique Agent provides feedback for
    self-correction, performance monitoring, and refining routing logic, enhancing
    system effectiveness.

                                                                                15

   ●​ Optimization Through Feedback and Flexibility: Evaluation capabilities for
      critique and model integration flexibility contribute to adaptive and
      self-improving system behavior.
   ●​ Additional Resource-Aware Optimizations: Other methods include Adaptive
      Tool Use & Selection, Contextual Pruning & Summarization, Proactive Resource
      Prediction, Cost-Sensitive Exploration in Multi-Agent Systems, Energy-Efficient
      Deployment, Parallelization & Distributed Computing Awareness, Learned
      Resource Allocation Policies, Graceful Degradation and Fallback Mechanisms,
      and Prioritization of Critical Tasks.


Conclusions
Resource-aware optimization is essential for the development of intelligent agents,
enabling efficient operation within real-world constraints. By managing computational,
temporal, and financial resources, agents can achieve optimal performance and
cost-effectiveness. Techniques such as dynamic model switching, adaptive tool use,
and contextual pruning are crucial for attaining these efficiencies. Advanced
strategies, including learned resource allocation policies and graceful degradation,
enhance an agent's adaptability and resilience under varying conditions. Integrating
these optimization principles into agent design is fundamental for building scalable,
robust, and sustainable AI systems.


References
   1.​ Google's Agent Development Kit (ADK): https://google.github.io/adk-docs/
   2.​ Gemini Flash 2.5 & Gemini 2.5 Pro: https://aistudio.google.com/
   3.​ OpenRouter: https://openrouter.ai/docs/quickstart




                                                                                   16

                                                                                       1




Chapter 17: Reasoning Techniques
This chapter delves into advanced reasoning methodologies for intelligent agents,
focusing on multi-step logical inferences and problem-solving. These techniques go
beyond simple sequential operations, making the agent's internal reasoning explicit.
This allows agents to break down problems, consider intermediate steps, and reach
more robust and accurate conclusions. A core principle among these advanced
methods is the allocation of increased computational resources during inference. This
means granting the agent, or the underlying LLM, more processing time or steps to
process a query and generate a response. Rather than a quick, single pass, the agent
can engage in iterative refinement, explore multiple solution paths, or utilize external
tools. This extended processing time during inference often significantly enhances
accuracy, coherence, and robustness, especially for complex problems requiring
deeper analysis and deliberation.

Practical Applications & Use Cases
Practical applications include:

   ●​ Complex Question Answering: Facilitating the resolution of multi-hop
      queries, which necessitate the integration of data from diverse sources and the
      execution of logical deductions, potentially involving the examination of
      multiple reasoning paths, and benefiting from extended inference time to
      synthesize information.
   ●​ Mathematical Problem Solving: Enabling the division of mathematical
      problems into smaller, solvable components, illustrating the step-by-step
      process, and employing code execution for precise computations, where
      prolonged inference enables more intricate code generation and validation.
   ●​ Code Debugging and Generation: Supporting an agent's explanation of its
      rationale for generating or correcting code, pinpointing potential issues
      sequentially, and iteratively refining the code based on test results
      (Self-Correction), leveraging extended inference time for thorough debugging
      cycles.
   ●​ Strategic Planning: Assisting in the development of comprehensive plans
      through reasoning across various options, consequences, and preconditions,
      and adjusting plans based on real-time feedback (ReAct), where extended
      deliberation can lead to more effective and reliable plans.
   ●​ Medical Diagnosis: Aiding an agent in systematically assessing symptoms, test
      outcomes, and patient histories to reach a diagnosis, articulating its reasoning
      at each phase, and potentially utilizing external instruments for data retrieval
                                                                                       1

                                                                                         2




      (ReAct). Increased inference time allows for a more comprehensive differential
      diagnosis.
   ●​ Legal Analysis: Supporting the analysis of legal documents and precedents to
      formulate arguments or provide guidance, detailing the logical steps taken, and
      ensuring logical consistency through self-correction. Increased inference time
      allows for more in-depth legal research and argument construction.


Reasoning techniques
To start, let's delve into the core reasoning techniques used to enhance the
problem-solving abilities of AI models..

Chain-of-Thought (CoT) prompting significantly enhances LLMs complex reasoning
abilities by mimicking a step-by-step thought process (see Fig. 1). Instead of providing
a direct answer, CoT prompts guide the model to generate a sequence of intermediate
reasoning steps. This explicit breakdown allows LLMs to tackle complex problems by
decomposing them into smaller, more manageable sub-problems. This technique
markedly improves the model's performance on tasks requiring multi-step reasoning,
such as arithmetic, common sense reasoning, and symbolic manipulation. A primary
advantage of CoT is its ability to transform a difficult, single-step problem into a series
of simpler steps, thereby increasing the transparency of the LLM's reasoning process.
This approach not only boosts accuracy but also offers valuable insights into the
model's decision-making, aiding in debugging and comprehension. CoT can be
implemented using various strategies, including offering few-shot examples that
demonstrate step-by-step reasoning or simply instructing the model to "think step by
step." Its effectiveness stems from its ability to guide the model's internal processing
toward a more deliberate and logical progression. As a result, Chain-of-Thought has
become a cornerstone technique for enabling advanced reasoning capabilities in
contemporary LLMs. This enhanced transparency and breakdown of complex
problems into manageable sub-problems is particularly important for autonomous
agents, as it enables them to perform more reliable and auditable actions in complex
environments.




                                                                                         2

                                                                                            3




Fig. 1: CoT prompt alongside the detailed, step-by-step response generated by the agent.

Let's see an example. It begins with a set of instructions that tell the AI how to think,
defining its persona and a clear five-step process to follow. This is the prompt that
initiates structured thinking.

Following that, the example shows the CoT process in action. The section labeled
"Agent's Thought Process" is the internal monologue where the model executes the
instructed steps. This is the literal "chain of thought." Finally, the "Agent's Final
Answer" is the polished, comprehensive output generated as a result of that careful,
step-by-step reasoning process


 You are an Information Retrieval Agent. Your goal is to answer the
 user's question comprehensively and accurately by thinking
 step-by-step.

 Here's the process you must follow:



                                                                                            3

                                                                        4




1. **Analyze the Query:** Understand the core subject and specific
requirements of the user's question. Identify key entities, keywords,
and the type of information being sought.
2. **Formulate Search Queries (for Knowledge Base):** Based on your
analysis, generate a list of precise search queries that you would
use to retrieve relevant information from a knowledge base or
external tools.
3. **Simulate Information Retrieval (Self-Correction/Reasoning):**
For each search query, mentally consider what kind of information you
expect to find. If you were to retrieve the content, what would be
the most relevant snippets? Think about potential ambiguities or
missing pieces.
4. **Synthesize Information:** Based on the simulated retrieval and
your understanding of the user's original query, synthesize the
gathered information into a coherent and complete answer. Ensure all
aspects of the query are addressed.
5. **Review and Refine:** Before finalizing, critically evaluate
your answer. Is it accurate? Is it comprehensive? Is it easy to
understand? Is it concise? If not, identify what needs to be improved
and how.

**User Query:** "Explain the main differences between classical
computers and quantum computers, and briefly describe a potential
application of quantum computing."

**Agent's Thought Process (Internal CoT Output - encouraged by the
prompt):**

**Thought 1 (Analyze Query):**
The user wants two things:
1. Main differences between classical and quantum computers.
2. One potential application of quantum computing.
Keywords: classical computers, quantum computers, differences,
potential application.

**Thought 2 (Formulate Search Queries):**
- "differences classical vs quantum computers"
- "how quantum computers work"
- "how classical computers work"
- "applications of quantum computing"

**Thought 3 (Simulate Information Retrieval & Identify Key
Concepts):**
- From "differences": Expect concepts like bits vs. qubits,
superposition, entanglement, probabilistic nature, computational
power for specific problems.
- From "how they work": Classical uses transistors/binary. Quantum

                                                                        4

                                                                                     5




uses quantum mechanics.
- From "applications": Expect drug discovery, material science,
cryptography, optimization.

**Thought 4 (Synthesize Information):**
Classical computers use bits (0 or 1), processing information
sequentially. Quantum computers use qubits, which can be 0, 1, or
both simultaneously (superposition), and can be entangled, allowing
for vastly different computational approaches. This enables them to
solve certain problems (like factoring large numbers or simulating
complex molecules) far more efficiently than classical computers. A
potential application is in drug discovery, where quantum computers
could simulate molecular interactions with unprecedented accuracy,
accelerating the development of new medicines.

**Thought 5 (Review and Refine):**
- Differences are covered (bits vs qubits, superposition,
entanglement, processing).
- Application is given (drug discovery).
- Is it brief? Yes.
- Is it clear? Yes.
- Looks good.

**Agent's Final Answer (Output to User):**

Classical computers process information using bits, which can be
either a 0 or a 1 at any given time, performing operations
sequentially. In contrast, quantum computers utilize qubits, which
can exist in multiple states simultaneously through superposition and
can be linked through entanglement, allowing for exponentially more
complex computations. This fundamental difference enables quantum
machines to tackle certain problems, such as simulating molecular
structures or breaking complex encryption, that are intractable for
even the most powerful classical supercomputers. A significant
potential application of quantum computing lies in drug discovery,
where its ability to precisely model molecular behavior could
revolutionize the development of new pharmaceuticals.


Tree-of-Thought (ToT) is a reasoning technique that builds upon Chain-of-Thought
(CoT). It allows large language models to explore multiple reasoning paths by
branching into different intermediate steps, forming a tree structure (see Fig. 2) This
approach supports complex problem-solving by enabling backtracking,
self-correction, and exploration of alternative solutions. Maintaining a tree of
possibilities allows the model to evaluate various reasoning trajectories before


                                                                                     5

                                                                                         6




finalizing an answer. This iterative process enhances the model's ability to handle
challenging tasks that require strategic planning and decision-making.




                           Fig.2: Example of Tree of Thoughts

Self-correction, also known as self-refinement, is a crucial aspect of an agent's
reasoning process, particularly within Chain-of-Thought prompting. It involves the
agent's internal evaluation of its generated content and intermediate thought
processes. This critical review enables the agent to identify ambiguities, information
gaps, or inaccuracies in its understanding or solutions. This iterative cycle of reviewing
and refining allows the agent to adjust its approach, improve response quality, and
ensure accuracy and thoroughness before delivering a final output. This internal
critique enhances the agent's capacity to produce reliable and high-quality results, as
demonstrated in examples within the dedicated Chapter 4.

This example demonstrates a systematic process of self-correction, crucial for
refining AI-generated content. It involves an iterative loop of drafting, reviewing
against original requirements, and implementing specific improvements. The
illustration begins by outlining the AI's function as a "Self-Correction Agent" with a

                                                                                         6

                                                                                     7




defined five-step analytical and revision workflow. Following this, a subpar "Initial
Draft" of a social media post is presented. The "Self-Correction Agent's Thought
Process" forms the core of the demonstration. Here, the Agent critically evaluates the
draft according to its instructions, pinpointing weaknesses such as low engagement
and a vague call to action. It then suggests concrete enhancements, including the use
of more impactful verbs and emojis. The process concludes with the "Final Revised
Content," a polished and notably improved version that integrates the self-identified
adjustments.


You are a highly critical and detail-oriented Self-Correction Agent.
Your task is to review a previously generated piece of content
against its original requirements and identify areas for improvement.
Your goal is to refine the content to be more accurate,
comprehensive, engaging, and aligned with the prompt.

Here's the process you must follow for self-correction:

1. **Understand Original Requirements:** Review the initial
prompt/requirements that led to the content's creation. What was the
*original intent*? What were the key constraints or goals?
2. **Analyze Current Content:** Read the provided content carefully.
3. **Identify Discrepancies/Weaknesses:** Compare the current
content against the original requirements. Look for:
   * **Accuracy Issues:** Are there any factual errors or misleading
statements?
   * **Completeness Gaps:** Does it fully address all aspects of the
original prompt? Is anything missing?
   * **Clarity & Coherence:** Is the language clear, concise, and
easy to understand? Does it flow logically?
   * **Tone & Style:** Does it match the desired tone and style
(e.g., professional, engaging, concise)?
   * **Engagement:** Is it captivating? Does it hold the reader's
attention?
   * **Redundancy/Verbosity:** Can any parts be condensed or removed
without losing meaning?
4. **Propose Specific Improvements:** For each identified weakness,
suggest concrete and actionable changes. Do not just state the
problem; propose a solution.
5. **Generate Revised Content:** Based on your proposed
improvements, rewrite the original content to incorporate all the
necessary changes. Ensure the revised content is polished and ready
for final use.

**Original Prompt/Requirements:** "Write a short, engaging social
media post (max 150 characters) announcing a new eco-friendly product

                                                                                     7

                                                                        8




line: 'GreenTech Gadgets'."

**Initial Draft (Content to be corrected):**

"We have new products. They are green and techy. Buy GreenTech
Gadgets now!"

**Self-Correction Agent's Thought Process (Internal CoT Output -
encouraged by the prompt):**

**Thought 1 (Understand Original Requirements):**
- Short, engaging social media post.
- Max 150 characters.
- Announce "GreenTech Gadgets" - a new eco-friendly product line.

**Thought 2 (Analyze Current Content):**
"We have new products. They are green and techy. Buy GreenTech
Gadgets now!" (64 characters)

**Thought 3 (Identify Discrepancies/Weaknesses):**
- **Engaging:** Not very engaging. Sounds generic.
- **Eco-friendly:** Implied by "green," but not explicitly
highlighted as a benefit.
- **Call to Action:** "Buy now!" is okay, but could be more
compelling.
- **Conciseness:** It's short, but could use stronger verbs/phrasing.
- **Impact:** Lacks excitement for a new product launch.

**Thought 4 (Propose Specific Improvements):**
- Make it more dynamic and exciting.
- Emphasize "eco-friendly" and "innovation."
- Use stronger verbs and more active voice.
- Add a clear, engaging call to action.
- Ensure it stays under 150 characters.

**Thought 5 (Generate Revised Content):**
Original: "We have new products. They are green and techy. Buy

                🌱
GreenTech Gadgets now!"
Revised idea 1: "   Discover GreenTech Gadgets! Our new eco-friendly
line blends innovation with sustainability. Go green, go smart! Shop
now! #EcoFriendly #GreenTech" (148 characters)
This revision directly addresses eco-friendliness, uses emojis for
engagement, adds a stronger call to action, and includes relevant
hashtags while staying within the character limit.

**Self-Correction Agent's Final Revised Content (Output to User):**


                                                                        8

                                                                                    9




🌱  Discover GreenTech Gadgets! Our new eco-friendly line blends
innovation with sustainability. Go green, go smart! Shop now!
#EcoFriendly #GreenTech



Fundamentally, this technique integrates a quality control measure directly into the
Agent's content generation, yielding more refined, precise, and superior results that
more effectively meet intricate user demands.

Program-Aided Language Models (PALMs) integrate LLMs with symbolic reasoning
capabilities. This integration allows the LLM to generate and execute code, such as
Python, as part of its problem-solving process. PALMs offload complex calculations,
logical operations, and data manipulation to a deterministic programming
environment. This approach utilizes the strengths of traditional programming for tasks
where LLMs might exhibit limitations in accuracy or consistency. When faced with
symbolic challenges, the model can produce code, execute it, and convert the results
into natural language. This hybrid methodology combines the LLM's understanding
and generation abilities with precise computation, enabling the model to address a
wider range of complex problems with potentially increased reliability and accuracy.
This is important for agents as it allows them to perform more accurate and reliable
actions by leveraging precise computation alongside their understanding and
generation capabilities. An example is the use of external tools within Google's ADK
for generating code.


from google.adk.tools import agent_tool
from google.adk.agents import Agent
from google.adk.tools import google_search
from google.adk.code_executors import BuiltInCodeExecutor

search_agent = Agent(
   model='gemini-2.0-flash',
   name='SearchAgent',
   instruction="""
   You're a specialist in Google Search
   """,
   tools=[google_search],
)
coding_agent = Agent(
   model='gemini-2.0-flash',
   name='CodeAgent',
   instruction="""
   You're a specialist in Code Execution

                                                                                    9

                                                                                      10




    """,
    code_executor=[BuiltInCodeExecutor],
)
root_agent = Agent(
   name="RootAgent",
   model="gemini-2.0-flash",
   description="Root Agent",
   tools=[agent_tool.AgentTool(agent=search_agent),
agent_tool.AgentTool(agent=coding_agent)],
)



Reinforcement Learning with Verifiable Rewards (RLVR): While effective, the
standard Chain-of-Thought (CoT) prompting used by many LLMs is a somewhat basic
approach to reasoning. It generates a single, predetermined line of thought without
adapting to the complexity of the problem. To overcome these limitations, a new class
of specialized "reasoning models" has been developed. These models operate
differently by dedicating a variable amount of "thinking" time before providing an
answer. This "thinking" process produces a more extensive and dynamic
Chain-of-Thought that can be thousands of tokens long. This extended reasoning
allows for more complex behaviors like self-correction and backtracking, with the
model dedicating more effort to harder problems. The key innovation enabling these
models is a training strategy called Reinforcement Learning from Verifiable Rewards
(RLVR). By training the model on problems with known correct answers (like math or
code), it learns through trial and error to generate effective, long-form reasoning. This
allows the model to evolve its problem-solving abilities without direct human
supervision. Ultimately, these reasoning models don't just produce an answer; they
generate a "reasoning trajectory" that demonstrates advanced skills like planning,
monitoring, and evaluation. This enhanced ability to reason and strategize is
fundamental to the development of autonomous AI agents, which can break down and
solve complex tasks with minimal human intervention.

ReAct (Reasoning and Acting, see Fig. 3, where KB stands for Knowledge Base) is a
paradigm that integrates Chain-of-Thought (CoT) prompting with an agent's ability to
interact with external environments through tools. Unlike generative models that
produce a final answer, a ReAct agent reasons about which actions to take. This
reasoning phase involves an internal planning process, similar to CoT, where the agent
determines its next steps, considers available tools, and anticipates outcomes.
Following this, the agent acts by executing a tool or function call, such as querying a
database, performing a calculation, or interacting with an API.


                                                                                      10

                                                                                    11




                               Fig.3: Reasoning and Act

ReAct operates in an interleaved manner: the agent executes an action, observes the
outcome, and incorporates this observation into subsequent reasoning. This iterative
loop of “Thought, Action, Observation, Thought...” allows the agent to dynamically
adapt its plan, correct errors, and achieve goals requiring multiple interactions with
the environment. This provides a more robust and flexible problem-solving approach
compared to linear CoT, as the agent responds to real-time feedback. By combining
language model understanding and generation with the capability to use tools, ReAct
enables agents to perform complex tasks requiring both reasoning and practical
execution. This approach is crucial for agents as it allows them to not only reason but
also to practically execute steps and interact with dynamic environments.

CoD (Chain of Debates) is a formal AI framework proposed by Microsoft where
multiple, diverse models collaborate and argue to solve a problem, moving beyond a
single AI's "chain of thought." This system operates like an AI council meeting, where
different models present initial ideas, critique each other's reasoning, and exchange
counterarguments. The primary goal is to enhance accuracy, reduce bias, and improve

                                                                                    11

                                                                                       12




the overall quality of the final answer by leveraging collective intelligence. Functioning
as an AI version of peer review, this method creates a transparent and trustworthy
record of the reasoning process. Ultimately, it represents a shift from a solitary Agent
providing an answer to a collaborative team of Agents working together to find a more
robust and validated solution.

GoD (Graph of Debates) is an advanced Agentic framework that reimagines
discussion as a dynamic, non-linear network rather than a simple chain. In this model,
arguments are individual nodes connected by edges that signify relationships like
'supports' or 'refutes,' reflecting the multi-threaded nature of real debate. This
structure allows new lines of inquiry to dynamically branch off, evolve independently,
and even merge over time. A conclusion is reached not at the end of a sequence, but
by identifying the most robust and well-supported cluster of arguments within the
entire graph. In this context, "well-supported" refers to knowledge that is firmly
established and verifiable. This can include information considered to be ground truth,
which means it is inherently correct and widely accepted as fact. Additionally, it
encompasses factual evidence obtained through search grounding, where
information is validated against external sources and real-world data. Finally, it also
pertains to a consensus reached by multiple models during a debate, indicating a high
degree of agreement and confidence in the information presented. This
comprehensive approach ensures a more robust and reliable foundation for the
information being discussed. This approach provides a more holistic and realistic
model for complex, collaborative AI reasoning.

MASS (optional advanced topic): An in-depth analysis of the design of multi-agent
systems reveals that their effectiveness is critically dependent on both the quality of
the prompts used to program individual agents and the topology that dictates their
interactions. The complexity of designing these systems is significant, as it involves a
vast and intricate search space. To address this challenge, a novel framework called
Multi-Agent System Search (MASS) was developed to automate and optimize the
design of MAS.
MASS employs a multi-stage optimization strategy that systematically navigates the
complex design space by interleaving prompt and topology optimization (see Fig. 4)

1. Block-Level Prompt Optimization: The process begins with a local optimization of
prompts for individual agent types, or "blocks," to ensure each component performs
its role effectively before being integrated into a larger system. This initial step is
crucial as it ensures that the subsequent topology optimization builds upon
well-performing agents, rather than suffering from the compounding impact of poorly

                                                                                       12

                                                                                      13




configured ones. For example, when optimizing for the HotpotQA dataset, the prompt
for a "Debator" agent is creatively framed to instruct it to act as an "expert
fact-checker for a major publication". Its optimized task is to meticulously review
proposed answers from other agents, cross-reference them with provided context
passages, and identify any inconsistencies or unsupported claims. This specialized
role-playing prompt, discovered during block-level optimization, aims to make the
debator agent highly effective at synthesizing information before it's even placed into
a larger workflow.

2. Workflow Topology Optimization: Following local optimization, MASS optimizes the
workflow topology by selecting and arranging different agent interactions from a
customizable design space. To make this search efficient, MASS employs an
influence-weighted method. This method calculates the "incremental influence" of
each topology by measuring its performance gain relative to a baseline agent and
uses these scores to guide the search toward more promising combinations. For
instance, when optimizing for the MBPP coding task, the topology search discovers
that a specific hybrid workflow is most effective. The best-found topology is not a
simple structure but a combination of an iterative refinement process with external
tool use. Specifically, it consists of one predictor agent that engages in several rounds
of reflection, with its code being verified by one executor agent that runs the code
against test cases. This discovered workflow shows that for coding, a structure that
combines iterative self-correction with external verification is superior to simpler MAS
designs.




Fig. 4: (Courtesy of the Authors): The Multi-Agent System Search (MASS) Framework
is a three-stage optimization process that navigates a search space encompassing
optimizable prompts (instructions and demonstrations) and configurable agent
                                                                                      13

                                                                                     14




building blocks (Aggregate, Reflect, Debate, Summarize, and Tool-use). The first
stage, Block-level Prompt Optimization, independently optimizes prompts for each
agent module. Stage two, Workflow Topology Optimization, samples valid system
configurations from an influence-weighted design space, integrating the optimized
prompts. The final stage, Workflow-level Prompt Optimization, involves a second
round of prompt optimization for the entire multi-agent system after the optimal
workflow from Stage two has been identified.

3. Workflow-Level Prompt Optimization: The final stage involves a global optimization
of the entire system's prompts. After identifying the best-performing topology, the
prompts are fine-tuned as a single, integrated entity to ensure they are tailored for
orchestration and that agent interdependencies are optimized. As an example, after
finding the best topology for the DROP dataset, the final optimization stage refines
the "Predictor" agent's prompt. The final, optimized prompt is highly detailed,
beginning by providing the agent with a summary of the dataset itself, noting its focus
on "extractive question answering" and "numerical information". It then includes
few-shot examples of correct question-answering behavior and frames the core
instruction as a high-stakes scenario: "You are a highly specialized AI tasked with
extracting critical numerical information for an urgent news report. A live broadcast is
relying on your accuracy and speed". This multi-faceted prompt, combining
meta-knowledge, examples, and role-playing, is tuned specifically for the final
workflow to maximize accuracy.

Key Findings and Principles: Experiments demonstrate that MAS optimized by MASS
significantly outperform existing manually designed systems and other automated
design methods across a range of tasks. The key design principles for effective MAS,
as derived from this research, are threefold:

   ●​ Optimize individual agents with high-quality prompts before composing them.
   ●​ Construct MAS by composing influential topologies rather than exploring an
      unconstrained search space.
   ●​ Model and optimize the interdependencies between agents through a final,
      workflow-level joint optimization.

Building on our discussion of key reasoning techniques, let's first examine a core
performance principle: the Scaling Inference Law for LLMs. This law states that a
model's performance predictably improves as the computational resources allocated
to it increase. We can see this principle in action in complex systems like Deep
Research, where an AI agent leverages these resources to autonomously investigate a


                                                                                     14

                                                                                 15




topic by breaking it down into sub-questions, using Web search as a tool, and
synthesizing its findings.

Deep Research. The term "Deep Research" describes a category of AI Agentic tools
designed to act as tireless, methodical research assistants. Major platforms in this
space include Perplexity AI, Google's Gemini research capabilities, and OpenAI's
advanced functions within ChatGPT (see Fig.5).




                 Fig. 5: Google Deep Research for Information Gathering

                                                                                 15

                                                                                        16




A fundamental shift introduced by these tools is the change in the search process
itself. A standard search provides immediate links, leaving the work of synthesis to
you. Deep Research operates on a different model. Here, you task an AI with a
complex query and grant it a "time budget"—usually a few minutes. In return for this
patience, you receive a detailed report.

During this time, the AI works on your behalf in an agentic way. It autonomously
performs a series of sophisticated steps that would be incredibly time-consuming for
a person:

   1.​ Initial Exploration: It runs multiple, targeted searches based on your initial
       prompt.
   2.​ Reasoning and Refinement: It reads and analyzes the first wave of results,
       synthesizes the findings, and critically identifies gaps, contradictions, or areas
       that require more detail.
   3.​ Follow-up Inquiry: Based on its internal reasoning, it conducts new, more
       nuanced searches to fill those gaps and deepen its understanding.
   4.​ Final Synthesis: After several rounds of this iterative searching and reasoning, it
       compiles all the validated information into a single, cohesive, and structured
       summary.

This systematic approach ensures a comprehensive and well-reasoned response,
significantly enhancing the efficiency and depth of information gathering, thereby
facilitating more agentic decision-making.


Scaling Inference Law
This critical principle dictates the relationship between an LLM's performance and the
computational resources allocated during its operational phase, known as inference.
The Inference Scaling Law differs from the more familiar scaling laws for training,
which focus on how model quality improves with increased data volume and
computational power during a model's creation. Instead, this law specifically examines
the dynamic trade-offs that occur when an LLM is actively generating an output or
answer.

A cornerstone of this law is the revelation that superior results can frequently be
achieved from a comparatively smaller LLM by augmenting the computational
investment at inference time. This doesn't necessarily mean using a more powerful

                                                                                        16

                                                                                       17




GPU, but rather employing more sophisticated or resource-intensive inference
strategies. A prime example of such a strategy is instructing the model to generate
multiple potential answers—perhaps through techniques like diverse beam search or
self-consistency methods—and then employing a selection mechanism to identify the
most optimal output. This iterative refinement or multiple-candidate generation
process demands more computational cycles but can significantly elevate the quality
of the final response.

This principle offers a crucial framework for informed and economically sound
decision-making in the deployment of Agents systems. It challenges the intuitive
notion that a larger model will always yield better performance. The law posits that a
smaller model, when granted a more substantial "thinking budget" during inference,
can occasionally surpass the performance of a much larger model that relies on a
simpler, less computationally intensive generation process. The "thinking budget" here
refers to the additional computational steps or complex algorithms applied during
inference, allowing the smaller model to explore a wider range of possibilities or apply
more rigorous internal checks before settling on an answer.

Consequently, the Scaling Inference Law becomes fundamental to constructing
efficient and cost-effective Agentic systems. It provides a methodology for
meticulously balancing several interconnected factors:

   ●​ Model Size: Smaller models are inherently less demanding in terms of memory
      and storage.
   ●​ Response Latency: While increased inference-time computation can add to
      latency, the law helps identify the point at which the performance gains
