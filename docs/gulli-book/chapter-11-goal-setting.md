# Chapter 11: Goal Setting and Monitoring

> From *Agentic Design Patterns — A Hands-On Guide to Building Intelligent Systems* by Antonio Gulli.
> Source: [`docs/Agentic_Design_Patterns.pdf`](../Agentic_Design_Patterns.pdf) (extracted 2026-04-23 via `pdftotext -layout`).
> Overview: [`docs/gulli-book-overview.md`](../gulli-book-overview.md).
> Our platform's status on this pattern: see [`wiki/patterns/`](../../wiki/patterns/).

---

        port=8000
    )


This Python script defines a single function called greet, which takes a person's name
and returns a personalized greeting. The @tool() decorator above this function
automatically registers it as a tool that an AI or another program can use. The
function's documentation string and type hints are used by FastMCP to tell the Agent
how the tool works, what inputs it needs, and what it will return.

When the script is executed, it starts the FastMCP server, which listens for requests
on localhost:8000. This makes the greet function available as a network service. An
agent could then be configured to connect to this server and use the greet tool to
generate greetings as part of a larger task. The server runs continuously until it is
manually stopped.


Consuming the FastMCP Server with an ADK Agent
An ADK agent can be set up as an MCP client to use a running FastMCP server. This
requires configuring HttpServerParameters with the FastMCP server's network
address, which is usually http://localhost:8000.

A tool_filter parameter can be included to restrict the agent's tool usage to specific
tools offered by the server, such as 'greet'. When prompted with a request like "Greet
John Doe," the agent's embedded LLM identifies the 'greet' tool available via MCP,
invokes it with the argument "John Doe," and returns the server's response. This
process demonstrates the integration of user-defined tools exposed through MCP
with an ADK agent.

To establish this configuration, an agent file (e.g., agent.py located in
./adk_agent_samples/fastmcp_client_agent/) is required. This file will instantiate an


                                                                                        12

ADK agent and use HttpServerParameters to establish a connection with the
operational FastMCP server.

# ./adk_agent_samples/fastmcp_client_agent/agent.py
import os
from google.adk.agents import LlmAgent
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset,
HttpServerParameters

# Define the FastMCP server's address.
# Make sure your fastmcp_server.py (defined previously) is running on
this port.
FASTMCP_SERVER_URL = "http://localhost:8000"

root_agent = LlmAgent(
   model='gemini-2.0-flash', # Or your preferred model
   name='fastmcp_greeter_agent',
   instruction='You are a friendly assistant that can greet people by
their name. Use the "greet" tool.',
   tools=[
       MCPToolset(
           connection_params=HttpServerParameters(
               url=FASTMCP_SERVER_URL,
           ),
           # Optional: Filter which tools from the MCP server are
exposed
           # For this example, we're expecting only 'greet'
           tool_filter=['greet']
       )
   ],
)



The script defines an Agent named fastmcp_greeter_agent that uses a Gemini
language model. It's given a specific instruction to act as a friendly assistant whose
purpose is to greet people. Crucially, the code equips this agent with a tool to perform
its task. It configures an MCPToolset to connect to a separate server running on
localhost:8000, which is expected to be the FastMCP server from the previous
example. The agent is specifically granted access to the greet tool hosted on that
server. In essence, this code sets up the client side of the system, creating an
intelligent agent that understands its goal is to greet people and knows exactly which
external tool to use to accomplish it.



                                                                                     13

Creating an __init__.py file within the fastmcp_client_agent directory is necessary. This
ensures the agent is recognized as a discoverable Python package for the ADK.

To begin, open a new terminal and run `python fastmcp_server.py` to start the
FastMCP server. Next, go to the parent directory of `fastmcp_client_agent` (for
example, `adk_agent_samples`) in your terminal and execute `adk web`. Once the
ADK Web UI loads in your browser, select the `fastmcp_greeter_agent` from the agent
menu. You can then test it by entering a prompt like "Greet John Doe." The agent will
use the `greet` tool on your FastMCP server to create a response.


At a Glance
What: To function as effective agents, LLMs must move beyond simple text
generation. They require the ability to interact with the external environment to access
current data and utilize external software. Without a standardized communication
method, each integration between an LLM and an external tool or data source
becomes a custom, complex, and non-reusable effort. This ad-hoc approach hinders
scalability and makes building complex, interconnected AI systems difficult and
inefficient.

Why: The Model Context Protocol (MCP) offers a standardized solution by acting as a
universal interface between LLMs and external systems. It establishes an open,
standardized protocol that defines how external capabilities are discovered and used.
Operating on a client-server model, MCP allows servers to expose tools, data
resources, and interactive prompts to any compliant client. LLM-powered applications
act as these clients, dynamically discovering and interacting with available resources
in a predictable manner. This standardized approach fosters an ecosystem of
interoperable and reusable components, dramatically simplifying the development of
complex agentic workflows.

Rule of thumb: Use the Model Context Protocol (MCP) when building complex,
scalable, or enterprise-grade agentic systems that need to interact with a diverse and
evolving set of external tools, data sources, and APIs. It is ideal when interoperability
between different LLMs and tools is a priority, and when agents require the ability to
dynamically discover new capabilities without being redeployed. For simpler
applications with a fixed and limited number of predefined functions, direct tool
function calling may be sufficient.




                                                                                       14

Visual summary




                           Fig.1: Model Context protocol


Key Takeaways
These are the key takeaways:

●​ The Model Context Protocol (MCP) is an open standard facilitating standardized
   communication between LLMs and external applications, data sources, and tools.
●​ It employs a client-server architecture, defining the methods for exposing and
   consuming resources, prompts, and tools.
●​ The Agent Development Kit (ADK) supports both utilizing existing MCP servers
   and exposing ADK tools via an MCP server.
●​ FastMCP simplifies the development and management of MCP servers,
   particularly for exposing tools implemented in Python.
●​ MCP Tools for Genmedia Services allows agents to integrate with Google Cloud's

                                                                               15

   generative media capabilities (Imagen, Veo, Chirp 3 HD, Lyria).
●​ MCP enables LLMs and agents to interact with real-world systems, access
   dynamic information, and perform actions beyond text generation.


Conclusion
The Model Context Protocol (MCP) is an open standard that facilitates communication
between Large Language Models (LLMs) and external systems. It employs a
client-server architecture, enabling LLMs to access resources, utilize prompts, and
execute actions through standardized tools. MCP allows LLMs to interact with
databases, manage generative media workflows, control IoT devices, and automate
financial services. Practical examples demonstrate setting up agents to communicate
with MCP servers, including filesystem servers and servers built with FastMCP,
illustrating its integration with the Agent Development Kit (ADK). MCP is a key
component for developing interactive AI agents that extend beyond basic language
capabilities.


References
1.​ Model Context Protocol (MCP) Documentation. (Latest). Model Context Protocol
    (MCP). https://google.github.io/adk-docs/mcp/
2.​ FastMCP Documentation. FastMCP. https://github.com/jlowin/fastmcp
3.​ MCP Tools for Genmedia Services. MCP Tools for Genmedia Services.
    https://google.github.io/adk-docs/mcp/#mcp-servers-for-google-cloud-genmedi
    a
4.​ MCP Toolbox for Databases Documentation. (Latest). MCP Toolbox for
    Databases. https://google.github.io/adk-docs/mcp/databases/




                                                                                 16

Chapter 11: Goal Setting and Monitoring
For AI agents to be truly effective and purposeful, they need more than just the ability
to process information or use tools; they need a clear sense of direction and a way to
know if they're actually succeeding. This is where the Goal Setting and Monitoring
pattern comes into play. It's about giving agents specific objectives to work towards
and equipping them with the means to track their progress and determine if those
objectives have been met.


Goal Setting and Monitoring Pattern Overview
Think about planning a trip. You don't just spontaneously appear at your destination.
You decide where you want to go (the goal state), figure out where you are starting
from (the initial state), consider available options (transportation, routes, budget), and
then map out a sequence of steps: book tickets, pack bags, travel to the
airport/station, board the transport, arrive, find accommodation, etc. This
step-by-step process, often considering dependencies and constraints, is
fundamentally what we mean by planning in agentic systems.

In the context of AI agents, planning typically involves an agent taking a high-level
objective and autonomously, or semi-autonomously, generating a series of
intermediate steps or sub-goals. These steps can then be executed sequentially or in
a more complex flow, potentially involving other patterns like tool use, routing, or
multi-agent collaboration. The planning mechanism might involve sophisticated
search algorithms, logical reasoning, or increasingly, leveraging the capabilities of
large language models (LLMs) to generate plausible and effective plans based on
their training data and understanding of tasks.

A good planning capability allows agents to tackle problems that aren't simple,
single-step queries. It enables them to handle multi-faceted requests, adapt to
changing circumstances by replanning, and orchestrate complex workflows. It's a
foundational pattern that underpins many advanced agentic behaviors, turning a
simple reactive system into one that can proactively work towards a defined objective.


Practical Applications & Use Cases
The Goal Setting and Monitoring pattern is essential for building agents that can
operate autonomously and reliably in complex, real-world scenarios. Here are some
practical applications:

                                                                                         1

●​ Customer Support Automation: An agent's goal might be to "resolve customer's
   billing inquiry." It monitors the conversation, checks database entries, and uses
   tools to adjust billing. Success is monitored by confirming the billing change and
   receiving positive customer feedback. If the issue isn't resolved, it escalates.
●​ Personalized Learning Systems: A learning agent might have the goal to
   "improve students’ understanding of algebra." It monitors the student's progress
   on exercises, adapts teaching materials, and tracks performance metrics like
   accuracy and completion time, adjusting its approach if the student struggles.
●​ Project Management Assistants: An agent could be tasked with "ensuring
   project milestone X is completed by Y date." It monitors task statuses, team
   communications, and resource availability, flagging delays and suggesting
   corrective actions if the goal is at risk.
●​ Automated Trading Bots: A trading agent's goal might be to "maximize portfolio
   gains while staying within risk tolerance." It continuously monitors market data, its
   current portfolio value, and risk indicators, executing trades when conditions align
   with its goals and adjusting strategy if risk thresholds are breached.
●​ Robotics and Autonomous Vehicles: An autonomous vehicle's primary goal is
   "safely transport passengers from A to B." It constantly monitors its environment
   (other vehicles, pedestrians, traffic signals), its own state (speed, fuel), and its
   progress along the planned route, adapting its driving behavior to achieve the
   goal safely and efficiently.
●​ Content Moderation: An agent's goal could be to "identify and remove harmful
   content from platform X." It monitors incoming content, applies classification
   models, and tracks metrics like false positives/negatives, adjusting its filtering
   criteria or escalating ambiguous cases to human reviewers.
This pattern is fundamental for agents that need to operate reliably, achieve specific
outcomes, and adapt to dynamic conditions, providing the necessary framework for
intelligent self-management.


Hands-On Code Example
To illustrate the Goal Setting and Monitoring pattern, we have an example using
LangChain and OpenAI APIs. This Python script outlines an autonomous AI agent
engineered to generate and refine Python code. Its core function is to produce
solutions for specified problems, ensuring adherence to user-defined quality
benchmarks.

It employs a "goal-setting and monitoring" pattern where it doesn't just generate code
once, but enters into an iterative cycle of creation, self-evaluation, and improvement.

                                                                                         2

The agent's success is measured by its own AI-driven judgment on whether the
generated code successfully meets the initial objectives. The ultimate output is a
polished, commented, and ready-to-use Python file that represents the culmination of
this refinement process.

Dependencies:

pip install langchain_openai openai python-dotenv
.env file with key in OPENAI_API_KEY



You can best understand this script by imagining it as an autonomous AI programmer
assigned to a project (see Fig. 1). The process begins when you hand the AI a detailed
project brief, which is the specific coding problem it needs to solve.

# MIT License
# Copyright (c) 2025 Mahtab Syed
# https://www.linkedin.com/in/mahtabsyed/

"""
Hands-On Code Example - Iteration 2
- To illustrate the Goal Setting and Monitoring pattern, we have an
example using LangChain and OpenAI APIs:

Objective: Build an AI Agent which can write code for a specified
use case based on specified goals:
- Accepts a coding problem (use case) in code or can be as input.
- Accepts a list of goals (e.g., "simple", "tested", "handles edge
cases") in code or can be input.
- Uses an LLM (like GPT-4o) to generate and refine Python code
until the goals are met. (I am using max 5 iterations, this could
be based on a set goal as well)
- To check if we have met our goals I am asking the LLM to judge
this and answer just True or False which makes it easier to stop
the iterations.
- Saves the final code in a .py file with a clean filename and a
header comment.
"""

import os
import random
REDACTED_a7b84d63
from pathlib import Path
from langchain_openai import ChatOpenAI


                                                                                     3

from dotenv import load_dotenv, find_dotenv

# 🔐  Load environment variables
_ = load_dotenv(find_dotenv())
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
   raise EnvironmentError("
environment variable.")
                              ❌Please set the OPENAI_API_KEY


# ✅ 📡Initialize OpenAI model
print("   Initializing OpenAI LLM (gpt-4o)...")
llm = ChatOpenAI(
   model="gpt-4o", # If you dont have access to got-4o use other
OpenAI LLMs
   temperature=0.3,
   openai_api_key=OPENAI_API_KEY,
)

# --- Utility Functions ---

def generate_prompt(
   use_case: str, goals: list[str], previous_code: str = "",
feedback: str = ""
) -> str:
   print("📝  Constructing prompt for code generation...")
   base_prompt = f"""
You are an AI coding agent. Your job is to write Python code based
on the following use case:

Use Case: {use_case}

Your goals are:
{chr(10).join(f"- {g.strip()}" for g in goals)}
"""

              🔄
    if previous_code:
        print("
refinement.")
                  Adding previous code to the prompt for

        base_prompt += f"\nPreviously generated
code:\n{previous_code}"

              📋
    if feedback:
        print("   Including feedback for revision.")
        base_prompt += f"\nFeedback on previous
version:\n{feedback}\n"

   base_prompt += "\nPlease return only the revised Python code. Do
not include comments or explanations outside the code."
   return base_prompt

                                                                      4

   print("🔍
def get_code_feedback(code: str, goals: list[str]) -> str:
             Evaluating code against the goals...")
   feedback_prompt = f"""
You are a Python code reviewer. A code snippet is shown below.
Based on the following goals:

{chr(10).join(f"- {g.strip()}" for g in goals)}

Please critique this code and identify if the goals are met.
Mention if improvements are needed for clarity, simplicity,
correctness, edge case handling, or test coverage.

Code:
{code}
"""
    return llm.invoke(feedback_prompt)

def goals_met(feedback_text: str, goals: list[str]) -> bool:
   """
   Uses the LLM to evaluate whether the goals have been met based
on the feedback text.
   Returns True or False (parsed from LLM output).
   """
   review_prompt = f"""
You are an AI reviewer.

Here are the goals:
{chr(10).join(f"- {g.strip()}" for g in goals)}

Here is the feedback on the code:
\"\"\"
{feedback_text}
\"\"\"

Based on the feedback above, have the goals been met?

Respond with only one word: True or False.
"""
    response = llm.invoke(review_prompt).content.strip().lower()
    return response == "true"

def clean_code_block(code: str) -> str:
   lines = code.strip().splitlines()
   if lines and lines[0].strip().startswith("```"):
       lines = lines[1:]
   if lines and lines[-1].strip() == "```":

                                                                    5

       lines = lines[:-1]
   return "\n".join(lines).strip()

def add_comment_header(code: str, use_case: str) -> str:
   comment = f"# This Python program implements the following use
case:\n# {use_case.strip()}\n"
   return comment + "\n" + code

def to_snake_case(text: str) -> str:
   text = re.sub(r"[^a-zA-Z0-9 ]", "", text)
   return re.sub(r"\s+", "_", text.strip().lower())


   print("💾
def save_code_to_file(code: str, use_case: str) -> str:
             Saving final code to file...")

   summary_prompt = (
       f"Summarize the following use case into a single lowercase
word or phrase, "
       f"no more than 10 characters, suitable for a Python
filename:\n\n{use_case}"
   )
   raw_summary = llm.invoke(summary_prompt).content.strip()
   short_name = re.sub(r"[^a-zA-Z0-9_]", "", raw_summary.replace("
", "_").lower())[:10]

   random_suffix = str(random.randint(1000, 9999))
   filename = f"{short_name}_{random_suffix}.py"
   filepath = Path.cwd() / filename

   with open(filepath, "w") as f:
       f.write(code)

   print(f"✅  Code saved to: {filepath}")
   return str(filepath)

# --- Main Agent Function ---

def run_code_agent(use_case: str, goals_input: str, max_iterations:
int = 5) -> str:
   goals = [g.strip() for g in goals_input.split(",")]


   print("🎯🎯
   print(f"\n    Use Case: {use_case}")
              Goals:")
   for g in goals:
       print(f" - {g}")

   previous_code = ""

                                                                      6

   feedback = ""


       print(f"\n===   🔁
   for i in range(max_iterations):
                        Iteration {i + 1} of {max_iterations} ===")
       prompt = generate_prompt(use_case, goals, previous_code,
feedback if isinstance(feedback, str) else feedback.content)

       print("🚧  Generating code...")
       code_response = llm.invoke(prompt)
       raw_code = code_response.content.strip()

       print("\n
"-" * 50)
                🧾
       code = clean_code_block(raw_code)
                   Generated Code:\n" + "-" * 50 + f"\n{code}\n" +


       print("\n📤 Submitting code for feedback review...")
       feedback = get_code_feedback(code, goals)

       print("\n📥 Feedback Received:\n" + "-" * 50 +
       feedback_text = feedback.content.strip()

f"\n{feedback_text}\n" + "-" * 50)


           print("
iteration.")
                   ✅
       if goals_met(feedback_text, goals):
                     LLM confirms goals are met. Stopping

           break

       print("
iteration...")
              🛠️ Goals not fully met. Preparing for next

       previous_code = code

   final_code = add_comment_header(code, use_case)
   return save_code_to_file(final_code, use_case)

# --- CLI Test Run ---


   print("\n🧠
if __name__ == "__main__":
               Welcome to the AI Code Generation Agent")

   # Example 1
   use_case_input = "Write code to find BinaryGap of a given
positive integer"
   goals_input = "Code simple to understand, Functionally correct,
Handles comprehensive edge cases, Takes positive integer input
only, prints the results with few examples"
   run_code_agent(use_case_input, goals_input)
