# Chapter 20: Prioritization

> From *Agentic Design Patterns — A Hands-On Guide to Building Intelligent Systems* by Antonio Gulli.
> Source: [`docs/Agentic_Design_Patterns.pdf`](../Agentic_Design_Patterns.pdf) (extracted 2026-04-23 via `pdftotext -layout`).
> Overview: [`docs/gulli-book-overview.md`](../gulli-book-overview.md).
> Our platform's status on this pattern: see [`wiki/patterns/`](../../wiki/patterns/).

---

strengths and weaknesses.

Evaluation Method             Strengths                    Weaknesses

Human Evaluation              Captures subtle behavior     Difficult to scale,
                                                           expensive, and
                                                           time-consuming, as it
                                                           considers subjective
                                                           human factors.

LLM-as-a-Judge                Consistent, efficient, and
                              scalable.                    Intermediate steps may be
                                                           overlooked. Limited by
                                                           LLM capabilities.

Automated Metrics             Scalable, efficient, and     Potential limitation in
                              objective                    capturing complete
                                                           capabilities.


Agents trajectories
Evaluating agents' trajectories is essential, as traditional software tests are
insufficient. Standard code yields predictable pass/fail results, whereas agents
operate probabilistically, necessitating qualitative assessment of both the final output
and the agent's trajectory—the sequence of steps taken to reach a solution.
Evaluating multi-agent systems is challenging because they are constantly in flux. This

                                                                                     10

requires developing sophisticated metrics that go beyond individual performance to
measure the effectiveness of communication and teamwork. Moreover, the
environments themselves are not static, demanding that evaluation methods,
including test cases, adapt over time.

This involves examining the quality of decisions, the reasoning process, and the
overall outcome. Implementing automated evaluations is valuable, particularly for
development beyond the prototype stage. Analyzing trajectory and tool use includes
evaluating the steps an agent employs to achieve a goal, such as tool selection,
strategies, and task efficiency. For example, an agent addressing a customer's
product query might ideally follow a trajectory involving intent determination,
database search tool use, result review, and report generation. The agent's actual
actions are compared to this expected, or ground truth, trajectory to identify errors
and inefficiencies. Comparison methods include exact match (requiring a perfect
match to the ideal sequence), in-order match (correct actions in order, allowing extra
steps), any-order match (correct actions in any order, allowing extra steps), precision
(measuring the relevance of predicted actions), recall (measuring how many essential
actions are captured), and single-tool use (checking for a specific action). Metric
selection depends on specific agent requirements, with high-stakes scenarios
potentially demanding an exact match, while more flexible situations might use an
in-order or any-order match.

Evaluation of AI agents involves two primary approaches: using test files and using
evalset files. Test files, in JSON format, represent single, simple agent-model
interactions or sessions and are ideal for unit testing during active development,
focusing on rapid execution and simple session complexity. Each test file contains a
single session with multiple turns, where a turn is a user-agent interaction including
the user’s query, expected tool use trajectory, intermediate agent responses, and final
response. For example, a test file might detail a user request to “Turn off device_2 in
the Bedroom,” specifying the agent’s use of a set_device_info tool with parameters
like location: Bedroom, device_id: device_2, and status: OFF, and an expected final
response of “I have set the device_2 status to off.” Test files can be organized into
folders and may include a test_config.json file to define evaluation criteria. Evalset
files utilize a dataset called an “evalset” to evaluate interactions, containing multiple
potentially lengthy sessions suited for simulating complex, multi-turn conversations
and integration tests. An evalset file comprises multiple “evals,” each representing a
distinct session with one or more “turns” that include user queries, expected tool use,
intermediate responses, and a reference final response. An example evalset might
include a session where the user first asks “What can you do?” and then says “Roll a

                                                                                       11

10 sided dice twice and then check if 9 is a prime or not,” defining expected roll\_die
tool calls and a check_prime tool call, along with the final response summarizing the
dice rolls and the prime check.

Multi-agents: Evaluating a complex AI system with multiple agents is much like
assessing a team project. Because there are many steps and handoffs, its complexity
is an advantage, allowing you to check the quality of work at each stage. You can
examine how well each individual "agent" performs its specific job, but you must also
evaluate how the entire system is performing as a whole.

To do this, you ask key questions about the team's dynamics, supported by concrete
examples:

   ●​ Are the agents cooperating effectively? For instance, after a 'Flight-Booking
      Agent' secures a flight, does it successfully pass the correct dates and
      destination to the 'Hotel-Booking Agent'? A failure in cooperation could lead to
      a hotel being booked for the wrong week.
   ●​ Did they create a good plan and stick to it? Imagine the plan is to first book a
      flight, then a hotel. If the 'Hotel Agent' tries to book a room before the flight is
      confirmed, it has deviated from the plan. You also check if an agent gets stuck,
      for example, endlessly searching for a "perfect" rental car and never moving on
      to the next step.
   ●​ Is the right agent being chosen for the right task? If a user asks about the
      weather for their trip, the system should use a specialized 'Weather Agent' that
      provides live data. If it instead uses a 'General Knowledge Agent' that gives a
      generic answer like "it's usually warm in summer," it has chosen the wrong tool
      for the job.
   ●​ Finally, does adding more agents improve performance? If you add a new
      'Restaurant-Reservation Agent' to the team, does it make the overall
      trip-planning better and more efficient? Or does it create conflicts and slow the
      system down, indicating a problem with scalability?.


From Agents to Advanced Contractors
Recently, it has been proposed (Agent Companion, gulli et al.) an evolution from
simple AI agents to advanced "contractors", moving from probabilistic, often
unreliable systems to more deterministic and accountable ones designed for complex,
high-stakes environments (see Fig.2).



                                                                                          12

Today's common AI agents operate on brief, underspecified instructions, which makes
them suitable for simple demonstrations but brittle in production, where ambiguity
leads to failure. The "contractor" model addresses this by establishing a rigorous,
formalized relationship between the user and the AI, built upon a foundation of clearly
defined and mutually agreed-upon terms, much like a legal service agreement in the
human world. This transformation is supported by four key pillars that collectively
ensure clarity, reliability, and robust execution of tasks that were previously beyond
the scope of autonomous systems.

First is the pillar of the Formalized Contract, a detailed specification that serves as the
single source of truth for a task. It goes far beyond a simple prompt. For example, a
contract for a financial analysis task wouldn't just say "analyze last quarter's sales"; it
would demand "a 20-page PDF report analyzing European market sales from Q1 2025,
including five specific data visualizations, a comparative analysis against Q1 2024, and
a risk assessment based on the included dataset of supply chain disruptions." This
contract explicitly defines the required deliverables, their precise specifications, the
acceptable data sources, the scope of work, and even the expected computational
cost and completion time, making the outcome objectively verifiable.

Second is the pillar of a Dynamic Lifecycle of Negotiation and Feedback. The contract
is not a static command but the start of a dialogue. The contractor agent can analyze
the initial terms and negotiate. For instance, if a contract demands the use of a
specific proprietary data source the agent cannot access, it can return feedback
stating, "The specified XYZ database is inaccessible. Please provide credentials or
approve the use of an alternative public database, which may slightly alter the data's
granularity." This negotiation phase, which also allows the agent to flag ambiguities or
potential risks, resolves misunderstandings before execution begins, preventing costly
failures and ensuring the final output aligns perfectly with the user's actual intent.




                                                                                        13

                   Fig. 2: Contract execution example among agents

The third pillar is Quality-Focused Iterative Execution. Unlike agents designed for
low-latency responses, a contractor prioritizes correctness and quality. It operates on
a principle of self-validation and correction. For a code generation contract, for
example, the agent would not just write the code; it would generate multiple
algorithmic approaches, compile and run them against a suite of unit tests defined
within the contract, score each solution on metrics like performance, security, and
readability, and only submit the version that passes all validation criteria. This internal
loop of generating, reviewing, and improving its own work until the contract's
specifications are met is crucial for building trust in its outputs.




                                                                                         14

Finally, the fourth pillar is Hierarchical Decomposition via Subcontracts. For tasks of
significant complexity, a primary contractor agent can act as a project manager,
breaking the main goal into smaller, more manageable sub-tasks. It achieves this by
generating new, formal "subcontracts." For example, a master contract to "build an
e-commerce mobile application" could be decomposed by the primary agent into
subcontracts for "designing the UI/UX," "developing the user authentication module,"
"creating the product database schema," and "integrating a payment gateway." Each
of these subcontracts is a complete, independent contract with its own deliverables
and specifications, which could be assigned to other specialized agents. This
structured decomposition allows the system to tackle immense, multifaceted projects
in a highly organized and scalable manner, marking the transition of AI from a simple
tool to a truly autonomous and reliable problem-solving engine.

Ultimately, this contractor framework reimagines AI interaction by embedding
principles of formal specification, negotiation, and verifiable execution directly into
the agent's core logic. This methodical approach elevates artificial intelligence from a
promising but often unpredictable assistant into a dependable system capable of
autonomously managing complex projects with auditable precision. By solving the
critical challenges of ambiguity and reliability, this model paves the way for deploying
AI in mission-critical domains where trust and accountability are paramount.


Google's ADK
Before concluding, let's look at a concrete example of a framework that supports
evaluation. Agent evaluation with Google's ADK (see Fig.3) can be conducted via three
methods: web-based UI (adk web) for interactive evaluation and dataset generation,
programmatic integration using pytest for incorporation into testing pipelines, and
direct command-line interface (adk eval) for automated evaluations suitable for
regular build generation and verification processes.




                                                                                      15

                       Fig.3: Evaluation Support for Google ADK

The web-based UI enables interactive session creation and saving into existing or new
eval sets, displaying evaluation status. Pytest integration allows running test files as
part of integration tests by calling AgentEvaluator.evaluate, specifying the agent
module and test file path.

The command-line interface facilitates automated evaluation by providing the agent
module path and eval set file, with options to specify a configuration file or print
detailed results. Specific evals within a larger eval set can be selected for execution
by listing them after the eval set filename, separated by commas.


At a Glance
What: Agentic systems and LLMs operate in complex, dynamic environments where
their performance can degrade over time. Their probabilistic and non-deterministic
nature means that traditional software testing is insufficient for ensuring reliability.
Evaluating dynamic multi-agent systems is a significant challenge because their
constantly changing nature and that of their environments demand the development
of adaptive testing methods and sophisticated metrics that can measure collaborative
success beyond individual performance. Problems like data drift, unexpected
interactions, tool calling, and deviations from intended goals can arise after


                                                                                          16

deployment. Continuous assessment is therefore necessary to measure an agent's
effectiveness, efficiency, and adherence to operational and safety requirements.

Why: A standardized evaluation and monitoring framework provides a systematic way
to assess and ensure the ongoing performance of intelligent agents. This involves
defining clear metrics for accuracy, latency, and resource consumption, like token
usage for LLMs. It also includes advanced techniques such as analyzing agentic
trajectories to understand the reasoning process and employing an LLM-as-a-Judge
for nuanced, qualitative assessments. By establishing feedback loops and reporting
systems, this framework allows for continuous improvement, A/B testing, and the
detection of anomalies or performance drift, ensuring the agent remains aligned with
its objectives.

Rule of thumb: Use this pattern when deploying agents in live, production
environments where real-time performance and reliability are critical. Additionally, use
it when needing to systematically compare different versions of an agent or its
underlying models to drive improvements, and when operating in regulated or
high-stakes domains requiring compliance, safety, and ethical audits. This pattern is
also suitable when an agent's performance may degrade over time due to changes in
data or the environment (drift), or when evaluating complex agentic behavior,
including the sequence of actions (trajectory) and the quality of subjective outputs
like helpfulness.

Visual summary




                    Fig.4: Evaluation and Monitoring design pattern


                                                                                      17

Key Takeaways
   ●​ Evaluating intelligent agents goes beyond traditional tests to continuously
      measure their effectiveness, efficiency, and adherence to requirements in
      real-world environments.
   ●​ Practical applications of agent evaluation include performance tracking in live
      systems, A/B testing for improvements, compliance audits, and detecting drift
      or anomalies in behavior.
   ●​ Basic agent evaluation involves assessing response accuracy, while real-world
      scenarios demand more sophisticated metrics like latency monitoring and
      token usage tracking for LLM-powered agents.
   ●​ Agent trajectories, the sequence of steps an agent takes, are crucial for
      evaluation, comparing actual actions against an ideal, ground-truth path to
      identify errors and inefficiencies.
   ●​ The ADK provides structured evaluation methods through individual test files
      for unit testing and comprehensive evalset files for integration testing, both
      defining expected agent behavior.
   ●​ Agent evaluations can be executed via a web-based UI for interactive testing,
      programmatically with pytest for CI/CD integration, or through a command-line
      interface for automated workflows.
   ●​ In order to make AI reliable for complex, high-stakes tasks, we must move from
      simple prompts to formal "contracts" that precisely define verifiable
      deliverables and scope. This structured agreement allows the Agents to
      negotiate, clarify ambiguities, and iteratively validate its own work, transforming
      it from an unpredictable tool into an accountable and trustworthy system.


Conclusions
In conclusion, effectively evaluating AI agents requires moving beyond simple
accuracy checks to a continuous, multi-faceted assessment of their performance in
dynamic environments. This involves practical monitoring of metrics like latency and
resource consumption, as well as sophisticated analysis of an agent's
decision-making process through its trajectory. For nuanced qualities like helpfulness,
innovative methods such as the LLM-as-a-Judge are becoming essential, while
frameworks like Google's ADK provide structured tools for both unit and integration
testing. The challenge intensifies with multi-agent systems, where the focus shifts to
evaluating collaborative success and effective cooperation.



                                                                                       18

To ensure reliability in critical applications, the paradigm is shifting from simple,
prompt-driven agents to advanced "contractors" bound by formal agreements. These
contractor agents operate on explicit, verifiable terms, allowing them to negotiate,
decompose tasks, and self-validate their work to meet rigorous quality standards. This
structured approach transforms agents from unpredictable tools into accountable
systems capable of handling complex, high-stakes tasks. Ultimately, this evolution is
crucial for building the trust required to deploy sophisticated agentic AI in
mission-critical domains.


References
Relevant research includes:
1.​ ADK Web: https://github.com/google/adk-web
2.​ ADK Evaluate: https://google.github.io/adk-docs/evaluate/
3.​ Survey on Evaluation of LLM-based Agents, https://arxiv.org/abs/2503.16416
4.​ Agent-as-a-Judge: Evaluate Agents with Agents, https://arxiv.org/abs/2410.10934
5.​ Agent Companion, gulli et al:
    https://www.kaggle.com/whitepaper-agent-companion




                                                                                   19

Chapter 20: Prioritization
In complex, dynamic environments, Agents frequently encounter numerous potential
actions, conflicting goals, and limited resources. Without a defined process for
determining the subsequent action, the agents may experience reduced efficiency,
operational delays, or failures to achieve key objectives. The prioritization pattern
addresses this issue by enabling agents to assess and rank tasks, objectives, or
actions based on their significance, urgency, dependencies, and established criteria.
This ensures the agents concentrate efforts on the most critical tasks, resulting in
enhanced effectiveness and goal alignment.


Prioritization Pattern Overview
Agents employ prioritization to effectively manage tasks, goals, and sub-goals,
guiding subsequent actions. This process facilitates informed decision-making when
addressing multiple demands, prioritizing vital or urgent activities over less critical
ones. It is particularly relevant in real-world scenarios where resources are
constrained, time is limited, and objectives may conflict.

The fundamental aspects of agent prioritization typically involve several elements.
First, criteria definition establishes the rules or metrics for task evaluation. These may
include urgency (time sensitivity of the task), importance (impact on the primary
objective), dependencies (whether the task is a prerequisite for others), resource
availability (readiness of necessary tools or information), cost/benefit analysis (effort
versus expected outcome), and user preferences for personalized agents. Second,
task evaluation involves assessing each potential task against these defined criteria,
utilizing methods ranging from simple rules to complex scoring or reasoning by LLMs.
Third, scheduling or selection logic refers to the algorithm that, based on the
evaluations, selects the optimal next action or task sequence, potentially utilizing a
queue or an advanced planning component. Finally, dynamic re-prioritization allows
the agent to modify priorities as circumstances change, such as the emergence of a
new critical event or an approaching deadline, ensuring agent adaptability and
responsiveness.

Prioritization can occur at various levels: selecting an overarching objective (high-level
goal prioritization), ordering steps within a plan (sub-task prioritization), or choosing
the next immediate action from available options (action selection). Effective
prioritization enables agents to exhibit more intelligent, efficient, and robust behavior,


                                                                                          1

especially in complex, multi-objective environments. This mirrors human team
organization, where managers prioritize tasks by considering input from all members.


Practical Applications & Use Cases
In various real-world applications, AI agents demonstrate a sophisticated use of
prioritization to make timely and effective decisions.

   ●​ Automated Customer Support: Agents prioritize urgent requests, like system
      outage reports, over routine matters, such as password resets. They may also
      give preferential treatment to high-value customers.
   ●​ Cloud Computing: AI manages and schedules resources by prioritizing
      allocation to critical applications during peak demand, while relegating less
      urgent batch jobs to off-peak hours to optimize costs.
   ●​ Autonomous Driving Systems: Continuously prioritize actions to ensure
      safety and efficiency. For example, braking to avoid a collision takes
      precedence over maintaining lane discipline or optimizing fuel efficiency.
   ●​ Financial Trading: Bots prioritize trades by analyzing factors like market
      conditions, risk tolerance, profit margins, and real-time news, enabling prompt
      execution of high-priority transactions.
   ●​ Project Management: AI agents prioritize tasks on a project board based on
      deadlines, dependencies, team availability, and strategic importance.
   ●​ Cybersecurity: Agents monitoring network traffic prioritize alerts by assessing
      threat severity, potential impact, and asset criticality, ensuring immediate
      responses to the most dangerous threats.
   ●​ Personal Assistant AIs: Utilize prioritization to manage daily lives, organizing
      calendar events, reminders, and notifications according to user-defined
      importance, upcoming deadlines, and current context.

These examples collectively illustrate how the ability to prioritize is fundamental to the
enhanced performance and decision-making capabilities of AI agents across a wide
spectrum of situations.


Hands-On Code Example
The following demonstrates the development of a Project Manager AI agent using
LangChain. This agent facilitates the creation, prioritization, and assignment of tasks




                                                                                          2

to team members, illustrating the application of large language models with bespoke
tools for automated project management.

import os
import asyncio
from typing import List, Optional, Dict, Type

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import Tool
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_react_agent
from langchain.memory import ConversationBufferMemory

