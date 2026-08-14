# Chapter 9: Learning and Adaptation

> From *Agentic Design Patterns — A Hands-On Guide to Building Intelligent Systems* by Antonio Gulli.
> Source: [`docs/Agentic_Design_Patterns.pdf`](../Agentic_Design_Patterns.pdf) (extracted 2026-04-23 via `pdftotext -layout`).
> Overview: [`docs/gulli-book-overview.md`](../gulli-book-overview.md).
> Our platform's status on this pattern: see [`wiki/patterns/`](../../wiki/patterns/).

---

Vertex Memory Bank
Memory Bank, a managed service in the Vertex AI Agent Engine, provides agents with
persistent, long-term memory. The service uses Gemini models to asynchronously
analyze conversation histories to extract key facts and user preferences.

This information is stored persistently, organized by a defined scope like user ID, and
intelligently updated to consolidate new data and resolve contradictions. Upon
starting a new session, the agent retrieves relevant memories through either a full
data recall or a similarity search using embeddings. This process allows an agent to
maintain continuity across sessions and personalize responses based on recalled
information.

The agent's runner interacts with the VertexAiMemoryBankService, which is initialized
first. This service handles the automatic storage of memories generated during the
agent's conversations. Each memory is tagged with a unique USER_ID and APP_NAME,
ensuring accurate retrieval in the future.

from google.adk.memory import VertexAiMemoryBankService

agent_engine_id = agent_engine.api_resource.name.split("/")[-1]

memory_service = VertexAiMemoryBankService(
   project="PROJECT_ID",
   location="LOCATION",
   agent_engine_id=agent_engine_id
)

session = await session_service.get_session(
   app_name=app_name,
   user_id="USER_ID",
   session_id=session.id
)
await memory_service.add_session_to_memory(session)



                                                                                      18

Memory Bank offers seamless integration with the Google ADK, providing an
immediate out-of-the-box experience. For users of other agent frameworks, such as
LangGraph and CrewAI, Memory Bank also offers support through direct API calls.
Online code examples demonstrating these integrations are readily available for
interested readers.


At a Glance
What: Agentic systems need to remember information from past interactions to
perform complex tasks and provide coherent experiences. Without a memory
mechanism, agents are stateless, unable to maintain conversational context, learn
from experience, or personalize responses for users. This fundamentally limits them to
simple, one-shot interactions, failing to handle multi-step processes or evolving user
needs. The core problem is how to effectively manage both the immediate, temporary
information of a single conversation and the vast, persistent knowledge gathered over
time.

Why: The standardized solution is to implement a dual-component memory system
that distinguishes between short-term and long-term storage. Short-term, contextual
memory holds recent interaction data within the LLM's context window to maintain
conversational flow. For information that must persist, long-term memory solutions
use external databases, often vector stores, for efficient, semantic retrieval. Agentic
frameworks like the Google ADK provide specific components to manage this, such as
Session for the conversation thread and State for its temporary data. A dedicated
MemoryService is used to interface with the long-term knowledge base, allowing the
agent to retrieve and incorporate relevant past information into its current context.

Rule of thumb: Use this pattern when an agent needs to do more than answer a
single question. It is essential for agents that must maintain context throughout a
conversation, track progress in multi-step tasks, or personalize interactions by
recalling user preferences and history. Implement memory management whenever the
agent is expected to learn or adapt based on past successes, failures, or newly
acquired information.

Visual summary




                                                                                     19

                    Fig.1: Memory management design pattern



Key Takeaways
To quickly recap the main points about memory management:
●​ Memory is super important for agents to keep track of things, learn, and
   personalize interactions.
●​ Conversational AI relies on both short-term memory for immediate context within
   a single chat and long-term memory for persistent knowledge across multiple
   sessions.
●​ Short-term memory (the immediate stuff) is temporary, often limited by the LLM's
   context window or how the framework passes context.
●​ Long-term memory (the stuff that sticks around) saves info across different chats
   using outside storage like vector databases and is accessed by searching.




                                                                                  20

●​ Frameworks like ADK have specific parts like Session (the chat thread), State
   (temporary chat data), and MemoryService (the searchable long-term
   knowledge) to manage memory.
●​ ADK's SessionService handles the whole life of a chat session, including its
   history (events) and temporary data (state).
●​ ADK's session.state is a dictionary for temporary chat data. Prefixes (user:, app:,
   temp:) tell you where the data belongs and if it sticks around.
●​ In ADK, you should update state by using EventActions.state_delta or output_key
   when adding events, not by changing the state dictionary directly.
●​ ADK's MemoryService is for putting info into long-term storage and letting agents
   search it, often using tools.
●​ LangChain offers practical tools like ConversationBufferMemory to automatically
   inject the history of a single conversation into a prompt, enabling an agent to
   recall immediate context.
●​ LangGraph enables advanced, long-term memory by using a store to save and
   retrieve semantic facts, episodic experiences, or even updatable procedural rules
   across different user sessions.
●​ Memory Bank is a managed service that provides agents with persistent,
   long-term memory by automatically extracting, storing, and recalling
   user-specific information to enable personalized, continuous conversations
   across frameworks like Google's ADK, LangGraph, and CrewAI.



Conclusion
This chapter dove into the really important job of memory management for agent
systems, showing the difference between the short-lived context and the knowledge
that sticks around for a long time. We talked about how these types of memory are
set up and where you see them used in building smarter agents that can remember
things. We took a detailed look at how Google ADK gives you specific pieces like
Session, State, and MemoryService to handle this. Now that we've covered how
agents can remember things, both short-term and long-term, we can move on to how
they can learn and adapt. The next pattern ​"Learning and Adaptation" is about an
agent changing how it thinks, acts, or what it knows, all based on new experiences or
data.


References
   1.​ ADK Memory, https://google.github.io/adk-docs/sessions/memory/

                                                                                    21

2.​ LangGraph Memory,
    https://langchain-ai.github.io/langgraph/concepts/memory/
3.​ Vertex AI Agent Engine Memory Bank,
    https://cloud.google.com/blog/products/ai-machine-learning/vertex-ai-memory
    -bank-in-public-preview




                                                                             22

Chapter 9: Learning and Adaptation
Learning and adaptation are pivotal for enhancing the capabilities of artificial
intelligence agents. These processes enable agents to evolve beyond predefined
parameters, allowing them to improve autonomously through experience and
environmental interaction. By learning and adapting, agents can effectively manage
novel situations and optimize their performance without constant manual intervention.
This chapter explores the principles and mechanisms underpinning agent learning
and adaptation in detail.


The big picture
Agents learn and adapt by changing their thinking, actions, or knowledge based on
new experiences and data. This allows agents to evolve from simply following
instructions to becoming smarter over time.

   ●​ Reinforcement Learning: Agents try actions and receive rewards for positive
      outcomes and penalties for negative ones, learning optimal behaviors in
      changing situations. Useful for agents controlling robots or playing games.
   ●​ Supervised Learning: Agents learn from labeled examples, connecting inputs
      to desired outputs, enabling tasks like decision-making and pattern recognition.
      Ideal for agents sorting emails or predicting trends.
   ●​ Unsupervised Learning: Agents discover hidden connections and patterns in
      unlabeled data, aiding in insights, organization, and creating a mental map of
      their environment. Useful for agents exploring data without specific guidance.
   ●​ Few-Shot/Zero-Shot Learning with LLM-Based Agents: Agents leveraging
      LLMs can quickly adapt to new tasks with minimal examples or clear
      instructions, enabling rapid responses to new commands or situations.
   ●​ Online Learning: Agents continuously update knowledge with new data,
      essential for real-time reactions and ongoing adaptation in dynamic
      environments. Critical for agents processing continuous data streams.
   ●​ Memory-Based Learning: Agents recall past experiences to adjust current
      actions in similar situations, enhancing context awareness and
      decision-making. Effective for agents with memory recall capabilities.

Agents adapt by changing strategy, understanding, or goals based on learning. This is
vital for agents in unpredictable, changing, or new environments.




                                                                                    1

Proximal Policy Optimization (PPO) is a reinforcement learning algorithm used to
train agents in environments with a continuous range of actions, like controlling a
robot's joints or a character in a game. Its main goal is to reliably and stably improve
an agent's decision-making strategy, known as its policy.

The core idea behind PPO is to make small, careful updates to the agent's policy. It
avoids drastic changes that could cause performance to collapse. Here's how it
works:

   1.​ Collect Data: The agent interacts with its environment (e.g., plays a game) using
       its current policy and collects a batch of experiences (state, action, reward).
   2.​ Evaluate a "Surrogate" Goal: PPO calculates how a potential policy update
       would change the expected reward. However, instead of just maximizing this
       reward, it uses a special "clipped" objective function.
   3.​ The "Clipping" Mechanism: This is the key to PPO's stability. It creates a "trust
       region" or a safe zone around the current policy. The algorithm is prevented
       from making an update that is too different from the current strategy. This
       clipping acts like a safety brake, ensuring the agent doesn't take a huge, risky
       step that undoes its learning.

In short, PPO balances improving performance with staying close to a known, working
strategy, which prevents catastrophic failures during training and leads to more stable
learning.

Direct Preference Optimization (DPO) is a more recent method designed
specifically for aligning Large Language Models (LLMs) with human preferences. It
offers a simpler, more direct alternative to using PPO for this task.

To understand DPO, it helps to first understand the traditional PPO-based alignment
method:

   ●​ The PPO Approach (Two-Step Process):
         1.​ Train a Reward Model: First, you collect human feedback data where
             people rate or compare different LLM responses (e.g., "Response A is
             better than Response B"). This data is used to train a separate AI model,
             called a reward model, whose job is to predict what score a human
             would give to any new response.
         2.​ Fine-Tune with PPO: Next, the LLM is fine-tuned using PPO. The LLM's
             goal is to generate responses that get the highest possible score from


                                                                                           2

             the reward model. The reward model acts as the "judge" in the training
             game.

This two-step process can be complex and unstable. For instance, the LLM might find
a loophole and learn to "hack" the reward model to get high scores for bad
responses.

   ●​ The DPO Approach (Direct Process): DPO skips the reward model entirely.
      Instead of translating human preferences into a reward score and then
      optimizing for that score, DPO uses the preference data directly to update the
      LLM's policy.
   ●​ It works by using a mathematical relationship that directly links preference data
      to the optimal policy. It essentially teaches the model: "Increase the probability
      of generating responses like the preferred one and decrease the probability of
      generating ones like the disfavored one."

In essence, DPO simplifies alignment by directly optimizing the language model on
human preference data. This avoids the complexity and potential instability of training
and using a separate reward model, making the alignment process more efficient and
robust.


Practical Applications & Use Cases
Adaptive agents exhibit enhanced performance in variable environments through
iterative updates driven by experiential data.

   ●​ Personalized assistant agents refine interaction protocols through
      longitudinal analysis of individual user behaviors, ensuring highly optimized
      response generation.
   ●​ Trading bot agents optimize decision-making algorithms by dynamically
      adjusting model parameters based on high-resolution, real-time market data,
      thereby maximizing financial returns and mitigating risk factors.
   ●​ Application agents optimize user interface and functionality through dynamic
      modification based on observed user behavior, resulting in increased user
      engagement and system intuitiveness.
   ●​ Robotic and autonomous vehicle agents enhance navigation and response
      capabilities by integrating sensor data and historical action analysis, enabling
      safe and efficient operation across diverse environmental conditions.
   ●​ Fraud detection agents improve anomaly detection by refining predictive
      models with newly identified fraudulent patterns, enhancing system security

                                                                                       3

      and minimizing financial losses.
   ●​ Recommendation agents improve content selection precision by employing
      user preference learning algorithms, providing highly individualized and
      contextually relevant recommendations.
   ●​ Game AI agents enhance player engagement by dynamically adapting
      strategic algorithms, thereby increasing game complexity and challenge.
   ●​ Knowledge Base Learning Agents: Agents can leverage Retrieval Augmented
      Generation (RAG) to maintain a dynamic knowledge base of problem
      descriptions and proven solutions (see the Chapter 14). By storing successful
      strategies and challenges encountered, the agent can reference this data
      during decision-making, enabling it to adapt to new situations more effectively
      by applying previously successful patterns or avoiding known pitfalls.


Case Study: The Self-Improving Coding Agent
(SICA)
The Self-Improving Coding Agent (SICA), developed by Maxime Robeyns, Laurence
Aitchison, and Martin Szummer, represents an advancement in agent-based learning,
demonstrating the capacity for an agent to modify its own source code. This contrasts
with traditional approaches where one agent might train another; SICA acts as both
the modifier and the modified entity, iteratively refining its code base to improve
performance across various coding challenges.
SICA's self-improvement operates through an iterative cycle (see Fig.1). Initially, SICA
reviews an archive of its past versions and their performance on benchmark tests. It
selects the version with the highest performance score, calculated based on a
weighted formula considering success, time, and computational cost. This selected
version then undertakes the next round of self-modification. It analyzes the archive to
identify potential improvements and then directly alters its codebase. The modified
agent is subsequently tested against benchmarks, with the results recorded in the
archive. This process repeats, facilitating learning directly from past performance.
This self-improvement mechanism allows SICA to evolve its capabilities without
requiring traditional training paradigms.




                                                                                       4

Fig.1: SICA's self-improvement, learning and adapting based on its past versions


SICA underwent significant self-improvement, leading to advancements in code
editing and navigation. Initially, SICA utilized a basic file-overwriting approach for
code changes. It subsequently developed a "Smart Editor" capable of more intelligent
and contextual edits. This evolved into a "Diff-Enhanced Smart Editor," incorporating
diffs for targeted modifications and pattern-based editing, and a "Quick Overwrite
Tool" to reduce processing demands.

SICA further implemented "Minimal Diff Output Optimization" and "Context-Sensitive
Diff Minimization," using Abstract Syntax Tree (AST) parsing for efficiency. Additionally,
a "SmartEditor Input Normalizer" was added. In terms of navigation, SICA
independently created an "AST Symbol Locator," using the code's structural map
(AST) to identify definitions within the codebase. Later, a "Hybrid Symbol Locator"
was developed, combining a quick search with AST checking. This was further
optimized via "Optimized AST Parsing in Hybrid Symbol Locator" to focus on relevant
code sections, improving search speed.(see Fig. 2)


                                                                                        5

Fig.2 : Performance across iterations. Key improvements are annotated with their
corresponding tool or agent modifications. (courtesy of Maxime Robeyns , Martin
Szummer , Laurence Aitchison)

SICA's architecture comprises a foundational toolkit for basic file operations,
command execution, and arithmetic calculations. It includes mechanisms for result
submission and the invocation of specialized sub-agents (coding, problem-solving,
and reasoning). These sub-agents decompose complex tasks and manage the LLM's
context length, especially during extended improvement cycles.

An asynchronous overseer, another LLM, monitors SICA's behavior, identifying
potential issues such as loops or stagnation. It communicates with SICA and can
intervene to halt execution if necessary. The overseer receives a detailed report of
SICA's actions, including a callgraph and a log of messages and tool actions, to
identify patterns and inefficiencies.

SICA's LLM organizes information within its context window, its short-term memory, in
a structured manner crucial to its operation. This structure includes a System Prompt
defining agent goals, tool and sub-agent documentation, and system instructions. A
Core Prompt contains the problem statement or instruction, content of open files, and
a directory map. Assistant Messages record the agent's step-by-step reasoning, tool
and sub-agent call records and results, and overseer communications. This
organization facilitates efficient information flow, enhancing LLM operation and

                                                                                       6

reducing processing time and costs. Initially, file changes were recorded as diffs,
showing only modifications and periodically consolidated.

SICA: A Look at the Code: Delving deeper into SICA's implementation reveals several
key design choices that underpin its capabilities. As discussed, the system is built with
a modular architecture, incorporating several sub-agents, such as a coding agent, a
problem-solver agent, and a reasoning agent. These sub-agents are invoked by the
main agent, much like tool calls, serving to decompose complex tasks and efficiently
manage context length, especially during those extended meta-improvement
iterations.

The project is actively developed and aims to provide a robust framework for those
interested in post-training LLMs on tool use and other agentic tasks, with the full code
available for further exploration and contribution at the
https://github.com/MaximeRobeyns/self_improving_coding_agent/ GitHub repository.

For security, the project strongly emphasizes Docker containerization, meaning the
agent runs within a dedicated Docker container. This is a crucial measure, as it
provides isolation from the host machine, mitigating risks like inadvertent file system
manipulation given the agent's ability to execute shell commands.

To ensure transparency and control, the system features robust observability through
an interactive webpage that visualizes events on the event bus and the agent's
callgraph. This offers comprehensive insights into the agent's actions, allowing users
to inspect individual events, read overseer messages, and collapse sub-agent traces
for clearer understanding.

In terms of its core intelligence, the agent framework supports LLM integration from
various providers, enabling experimentation with different models to find the best fit
for specific tasks. Finally, a critical component is the asynchronous overseer, an LLM
that runs concurrently with the main agent. This overseer periodically assesses the
agent's behavior for pathological deviations or stagnation and can intervene by
sending notifications or even cancelling the agent's execution if necessary. It receives
a detailed textual representation of the system's state, including a callgraph and an
event stream of LLM messages, tool calls, and responses, which allows it to detect
inefficient patterns or repeated work.

A notable challenge in the initial SICA implementation was prompting the LLM-based
agent to independently propose novel, innovative, feasible, and engaging
modifications during each meta-improvement iteration. This limitation, particularly in

                                                                                          7

fostering open-ended learning and authentic creativity in LLM agents, remains a key
area of investigation in current research.


AlphaEvolve and OpenEvolve
AlphaEvolve is an AI agent developed by Google designed to discover and optimize
algorithms. It utilizes a combination of LLMs, specifically Gemini models (Flash and
Pro), automated evaluation systems, and an evolutionary algorithm framework. This
system aims to advance both theoretical mathematics and practical computing
applications.

AlphaEvolve employs an ensemble of Gemini models. Flash is used for generating a
wide range of initial algorithm proposals, while Pro provides more in-depth analysis
and refinement. Proposed algorithms are then automatically evaluated and scored
based on predefined criteria. This evaluation provides feedback that is used to
iteratively improve the solutions, leading to optimized and novel algorithms.

In practical computing, AlphaEvolve has been deployed within Google's infrastructure.
It has demonstrated improvements in data center scheduling, resulting in a 0.7%
reduction in global compute resource usage. It has also contributed to hardware
