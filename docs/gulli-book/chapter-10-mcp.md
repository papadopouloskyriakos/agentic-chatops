# Chapter 10: Model Context Protocol (MCP)

> From *Agentic Design Patterns — A Hands-On Guide to Building Intelligent Systems* by Antonio Gulli.
> Source: [`docs/Agentic_Design_Patterns.pdf`](../Agentic_Design_Patterns.pdf) (extracted 2026-04-23 via `pdftotext -layout`).
> Overview: [`docs/gulli-book-overview.md`](../gulli-book-overview.md).
> Our platform's status on this pattern: see [`wiki/patterns/`](../../wiki/patterns/).

---

design by suggesting optimizations for Verilog code in upcoming Tensor Processing
Units (TPUs). Furthermore, AlphaEvolve has accelerated AI performance, including a
23% speed improvement in a core kernel of the Gemini architecture and up to 32.5%
optimization of low-level GPU instructions for FlashAttention.

In the realm of fundamental research, AlphaEvolve has contributed to the discovery of
new algorithms for matrix multiplication, including a method for 4x4 complex-valued
matrices that uses 48 scalar multiplications, surpassing previously known solutions. In
broader mathematical research, it has rediscovered existing state-of-the-art solutions
to over 50 open problems in 75% of cases and improved upon existing solutions in
20% of cases, with examples including advancements in the kissing number problem.

OpenEvolve is an evolutionary coding agent that leverages LLMs (see Fig.3) to
iteratively optimize code. It orchestrates a pipeline of LLM-driven code generation,
evaluation, and selection to continuously enhance programs for a wide range of tasks.
A key aspect of OpenEvolve is its capability to evolve entire code files, rather than
being limited to single functions. The agent is designed for versatility, offering support
for multiple programming languages and compatibility with OpenAI-compatible APIs

                                                                                         8

for any LLM. Furthermore, it incorporates multi-objective optimization, allows for
flexible prompt engineering, and is capable of distributed evaluation to efficiently
handle complex coding challenges.




Fig. 3: The OpenEvolve internal architecture is managed by a controller. This controller
   orchestrates several key components: the program sampler, Program Database,
 Evaluator Pool, and LLM Ensembles. Its primary function is to facilitate their learning
                  and adaptation processes to enhance code quality.


This code snippet uses the OpenEvolve library to perform evolutionary optimization on
a program. It initializes the OpenEvolve system with paths to an initial program, an
evaluation file, and a configuration file. The evolve.run(iterations=1000) line starts the
evolutionary process, running for 1000 iterations to find an improved version of the
program. Finally, it prints the metrics of the best program found during the evolution,
formatted to four decimal places.


 from openevolve import OpenEvolve

                                                                                        9

 # Initialize the system
 evolve = OpenEvolve(
    initial_program_path="path/to/initial_program.py",
    evaluation_file="path/to/evaluator.py",
    config_path="path/to/config.yaml"
 )

 # Run the evolution
 best_program = await evolve.run(iterations=1000)
 print(f"Best program metrics:")
 for name, value in best_program.metrics.items():
    print(f" {name}: {value:.4f}")


At a Glance
What: AI agents often operate in dynamic and unpredictable environments where
pre-programmed logic is insufficient. Their performance can degrade when faced
with novel situations not anticipated during their initial design. Without the ability to
learn from experience, agents cannot optimize their strategies or personalize their
interactions over time. This rigidity limits their effectiveness and prevents them from
achieving true autonomy in complex, real-world scenarios.

Why: The standardized solution is to integrate learning and adaptation mechanisms,
transforming static agents into dynamic, evolving systems. This allows an agent to
autonomously refine its knowledge and behaviors based on new data and interactions.
Agentic systems can use various methods, from reinforcement learning to more
advanced techniques like self-modification, as seen in the Self-Improving Coding Agent
(SICA). Advanced systems like Google's AlphaEvolve leverage LLMs and evolutionary
algorithms to discover entirely new and more efficient solutions to complex problems. By
continuously learning, agents can master new tasks, enhance their performance, and
adapt to changing conditions without requiring constant manual reprogramming.

Rule of thumb: Use this pattern when building agents that must operate in dynamic,
uncertain, or evolving environments. It is essential for applications requiring
personalization, continuous performance improvement, and the ability to handle novel
situations autonomously.

Visual summary




                                                                                            10

                       Fig.4: Learning and adapting pattern



Key Takeaways
●​ Learning and Adaptation are about agents getting better at what they do and
   handling new situations by using their experiences.
●​ "Adaptation" is the visible change in an agent's behavior or knowledge that
   comes from learning.
●​ SICA, the Self-Improving Coding Agent, self-improves by modifying its code
   based on past performance. This led to tools like the Smart Editor and AST
   Symbol Locator.
●​ Having specialized "sub-agents" and an "overseer" helps these self-improving
   systems manage big tasks and stay on track.
●​ The way an LLM's "context window" is set up (with system prompts, core prompts,
   and assistant messages) is super important for how efficiently agents work.
●​ This pattern is vital for agents that need to operate in environments that are
   always changing, uncertain, or require a personal touch.

                                                                                 11

●​ Building agents that learn often means hooking them up with machine learning
   tools and managing how data flows.
●​ An agent system, equipped with basic coding tools, can autonomously edit itself,
   and thereby improve its performance on benchmark tasks
●​ AlphaEvolve is Google's AI agent that leverages LLMs and an evolutionary
   framework to autonomously discover and optimize algorithms, significantly
   enhancing both fundamental research and practical computing applications..

Conclusion
This chapter examines the crucial roles of learning and adaptation in Artificial
Intelligence. AI agents enhance their performance through continuous data
acquisition and experience. The Self-Improving Coding Agent (SICA) exemplifies this
by autonomously improving its capabilities through code modifications.

We have reviewed the fundamental components of agentic AI, including architecture,
applications, planning, multi-agent collaboration, memory management, and learning
and adaptation. Learning principles are particularly vital for coordinated improvement
in multi-agent systems. To achieve this, tuning data must accurately reflect the
complete interaction trajectory, capturing the individual inputs and outputs of each
participating agent.

These elements contribute to significant advancements, such as Google's
AlphaEvolve. This AI system independently discovers and refines algorithms by LLMs,
automated assessment, and an evolutionary approach, driving progress in scientific
research and computational techniques. Such patterns can be combined to construct
sophisticated AI systems. Developments like AlphaEvolve demonstrate that
autonomous algorithmic discovery and optimization by AI agents are attainable.


References
1.​ Sutton, R. S., & Barto, A. G. (2018). Reinforcement Learning: An Introduction. MIT
    Press.
2.​ Goodfellow, I., Bengio, Y., & Courville, A. (2016). Deep Learning. MIT Press.
3.​ Mitchell, T. M. (1997). Machine Learning. McGraw-Hill.
4.​ Proximal Policy Optimization Algorithms by John Schulman, Filip Wolski, Prafulla
    Dhariwal, Alec Radford, and Oleg Klimov. You can find it on arXiv:
    https://arxiv.org/abs/1707.06347



                                                                                       12

5.​ Robeyns, M., Aitchison, L., & Szummer, M. (2025). A Self-Improving Coding Agent.
    arXiv:2504.15228v2. https://arxiv.org/pdf/2504.15228
    https://github.com/MaximeRobeyns/self_improving_coding_agent
6.​ AlphaEvolve blog,
    https://deepmind.google/discover/blog/alphaevolve-a-gemini-powered-coding-ag
    ent-for-designing-advanced-algorithms/
7.​ OpenEvolve, https://github.com/codelion/openevolve




                                                                                  13

Chapter 10: Model Context Protocol
To enable LLMs to function effectively as agents, their capabilities must extend
beyond multimodal generation. Interaction with the external environment is necessary,
including access to current data, utilization of external software, and execution of
specific operational tasks. The Model Context Protocol (MCP) addresses this need by
providing a standardized interface for LLMs to interface with external resources. This
protocol serves as a key mechanism to facilitate consistent and predictable
integration.


MCP Pattern Overview
Imagine a universal adapter that allows any LLM to plug into any external system,
database, or tool without a custom integration for each one. That's essentially what
the Model Context Protocol (MCP) is. It's an open standard designed to standardize
how LLMs like Gemini, OpenAI's GPT models, Mixtral, and Claude communicate with
external applications, data sources, and tools. Think of it as a universal connection
mechanism that simplifies how LLMs obtain context, execute actions, and interact
with various systems.

MCP operates on a client-server architecture. It defines how different elements—data
(referred to as resources), interactive templates (which are essentially prompts), and
actionable functions (known as tools)—are exposed by an MCP server. These are then
consumed by an MCP client, which could be an LLM host application or an AI agent
itself. This standardized approach dramatically reduces the complexity of integrating
LLMs into diverse operational environments.

However, MCP is a contract for an "agentic interface," and its effectiveness depends
heavily on the design of the underlying APIs it exposes. There is a risk that developers
simply wrap pre-existing, legacy APIs without modification, which can be suboptimal
for an agent. For example, if a ticketing system's API only allows retrieving full ticket
details one by one, an agent asked to summarize high-priority tickets will be slow and
inaccurate at high volumes. To be truly effective, the underlying API should be
improved with deterministic features like filtering and sorting to help the
non-deterministic agent work efficiently. This highlights that agents do not magically
replace deterministic workflows; they often require stronger deterministic support to
succeed.




                                                                                        1

Furthermore, MCP can wrap an API whose input or output is still not inherently
understandable by the agent. An API is only useful if its data format is agent-friendly,
a guarantee that MCP itself does not enforce. For instance, creating an MCP server
for a document store that returns files as PDFs is mostly useless if the consuming
agent cannot parse PDF content. The better approach would be to first create an API
that returns a textual version of the document, such as Markdown, which the agent
can actually read and process. This demonstrates that developers must consider not
just the connection, but the nature of the data being exchanged to ensure true
compatibility.


MCP vs. Tool Function Calling
The Model Context Protocol (MCP) and tool function calling are distinct mechanisms
that enable LLMs to interact with external capabilities (including tools) and execute
actions. While both serve to extend LLM capabilities beyond text generation, they
differ in their approach and level of abstraction.

Tool function calling can be thought of as a direct request from an LLM to a specific,
pre-defined tool or function. Note that in this context we use the words "tool" and
"function” interchangeably. This interaction is characterized by a one-to-one
communication model, where the LLM formats a request based on its understanding
of a user's intent requiring external action. The application code then executes this
request and returns the result to the LLM. This process is often proprietary and varies
across different LLM providers.

In contrast, the Model Context Protocol (MCP) operates as a standardized interface
for LLMs to discover, communicate with, and utilize external capabilities. It functions
as an open protocol that facilitates interaction with a wide range of tools and systems,
aiming to establish an ecosystem where any compliant tool can be accessed by any
compliant LLM. This fosters interoperability, composability and reusability across
different systems and implementations. By adopting a federated model, we
significantly improve interoperability and unlock the value of existing assets. This
strategy allows us to bring disparate and legacy services into a modern ecosystem
simply by wrapping them in an MCP-compliant interface. These services continue to
operate independently, but can now be composed into new applications and
workflows, with their collaboration orchestrated by LLMs. This fosters agility and
reusability without requiring costly rewrites of foundational systems.



                                                                                           2

Here's a breakdown of the fundamental distinctions between MCP and tool function
calling:

      Feature            Tool Function Calling         Model Context Protocol (MCP)


 Standardization      Proprietary and             An open, standardized protocol,
                      vendor-specific. The format promoting interoperability
                      and implementation differ   between different LLMs and tools.
                      across LLM providers.


 Scope                A direct mechanism for an       A broader framework for how
                      LLM to request the              LLMs and external tools discover
                      execution of a specific,        and communicate with each
                      predefined function.            other.


 Architecture         A one-to-one interaction        A client-server architecture where
                      between the LLM and the         LLM-powered applications
                      application's tool-handling     (clients) can connect to and utilize
                      logic.                          various MCP servers (tools).


 Discovery            The LLM is explicitly told      Enables dynamic discovery of
                      which tools are available       available tools. An MCP client can
                      within the context of a         query a server to see what
                      specific conversation.          capabilities it offers.


 Reusability          Tool integrations are often     Promotes the development of
                      tightly coupled with the        reusable, standalone "MCP
                      specific application and        servers" that can be accessed by
                      LLM being used.                 any compliant application.

Think of tool function calling as giving an AI a specific set of custom-built tools, like a
particular wrench and screwdriver. This is efficient for a workshop with a fixed set of
tasks. MCP (Model Context Protocol), on the other hand, is like creating a universal,
standardized power outlet system. It doesn't provide the tools itself, but it allows any
compliant tool from any manufacturer to plug in and work, enabling a dynamic and
ever-expanding workshop.


                                                                                              3

In short, function calling provides direct access to a few specific functions, while MCP
is the standardized communication framework that lets LLMs discover and use a vast
range of external resources. For simple applications, specific tools are enough; for
complex, interconnected AI systems that need to adapt, a universal standard like MCP
is essential.


Additional considerations for MCP
While MCP presents a powerful framework, a thorough evaluation requires
considering several crucial aspects that influence its suitability for a given use case.
Let's see some aspects in more details:

   ●​ Tool vs. Resource vs. Prompt: It's important to understand the specific roles
      of these components. A resource is static data (e.g., a PDF file, a database
      record). A tool is an executable function that performs an action (e.g., sending
      an email, querying an API). A prompt is a template that guides the LLM in how
      to interact with a resource or tool, ensuring the interaction is structured and
      effective.
   ●​ Discoverability: A key advantage of MCP is that an MCP client can dynamically
      query a server to learn what tools and resources it offers. This "just-in-time"
      discovery mechanism is powerful for agents that need to adapt to new
      capabilities without being redeployed.
   ●​ Security: Exposing tools and data via any protocol requires robust security
      measures. An MCP implementation must include authentication and
      authorization to control which clients can access which servers and what
      specific actions they are permitted to perform.
   ●​ Implementation: While MCP is an open standard, its implementation can be
      complex. However, providers are beginning to simplify this process. For
      example, some model providers like Anthropic or FastMCP offer SDKs that
      abstract away much of the boilerplate code, making it easier for developers to
      create and connect MCP clients and servers.
   ●​ Error Handling: A comprehensive error-handling strategy is critical. The
      protocol must define how errors (e.g., tool execution failure, unavailable server,
      invalid request) are communicated back to the LLM so it can understand the
      failure and potentially try an alternative approach.
   ●​ Local vs. Remote Server: MCP servers can be deployed locally on the same
      machine as the agent or remotely on a different server. A local server might be
      chosen for speed and security with sensitive data, while a remote server


                                                                                           4

      architecture allows for shared, scalable access to common tools across an
      organization.
   ●​ On-demand vs. Batch: MCP can support both on-demand, interactive
      sessions and larger-scale batch processing. The choice depends on the
      application, from a real-time conversational agent needing immediate tool
      access to a data analysis pipeline that processes records in batches.
   ●​ Transportation Mechanism: The protocol also defines the underlying
      transport layers for communication. For local interactions, it uses JSON-RPC
      over STDIO (standard input/output) for efficient inter-process communication.
      For remote connections, it leverages web-friendly protocols like Streamable
      HTTP and Server-Sent Events (SSE) to enable persistent and efficient
      client-server communication.

The Model Context Protocol uses a client-server model to standardize information
flow. Understanding component interaction is key to MCP's advanced agentic
behavior:

   1.​ Large Language Model (LLM): The core intelligence. It processes user
        requests, formulates plans, and decides when it needs to access external
        information or perform an action.
   2.​ MCP Client: This is an application or wrapper around the LLM. It acts as the
        intermediary, translating the LLM's intent into a formal request that conforms to
        the MCP standard. It is responsible for discovering, connecting to, and
        communicating with MCP Servers.
   3.​ MCP Server: This is the gateway to the external world. It exposes a set of tools,
        resources, and prompts to any authorized MCP Client. Each server is typically
        responsible for a specific domain, such as a connection to a company's internal
        database, an email service, or a public API.
   4.​ ​Optional Third-Party (3P) Service: This represents the actual external tool,
        application, or data source that the MCP Server manages and exposes. It is the
        ultimate endpoint that performs the requested action, such as querying a
        proprietary database, interacting with a SaaS platform, or calling a public
        weather API.

The interaction flows as follows:

   1.​ Discovery: The MCP Client, on behalf of the LLM, queries an MCP Server to
       ask what capabilities it offers. The server responds with a manifest listing its
       available tools (e.g., send_email), resources (e.g., customer_database), and
       prompts.

                                                                                          5

   2.​ Request Formulation: The LLM determines that it needs to use one of the
       discovered tools. For instance, it decides to send an email. It formulates a
       request, specifying the tool to use (send_email) and the necessary parameters
       (recipient, subject, body).
   3.​ Client Communication: The MCP Client takes the LLM's formulated request
       and sends it as a standardized call to the appropriate MCP Server.
   4.​ Server Execution: The MCP Server receives the request. It authenticates the
       client, validates the request, and then executes the specified action by
       interfacing with the underlying software (e.g., calling the send() function of an
       email API).
   5.​ Response and Context Update: After execution, the MCP Server sends a
       standardized response back to the MCP Client. This response indicates
       whether the action was successful and includes any relevant output (e.g., a
       confirmation ID for the sent email). The client then passes this result back to
       the LLM, updating its context and enabling it to proceed with the next step of
       its task.


Practical Applications & Use Cases
MCP significantly broadens AI/LLM capabilities, making them more versatile and
powerful. Here are nine key use cases:
●​ Database Integration: MCP allows LLMs and agents to seamlessly access and
   interact with structured data in databases. For instance, using the MCP Toolbox
   for Databases, an agent can query Google BigQuery datasets to retrieve real-time
   information, generate reports, or update records, all driven by natural language
   commands.
●​ Generative Media Orchestration: MCP enables agents to integrate with
   advanced generative media services. Through MCP Tools for Genmedia Services,
   an agent can orchestrate workflows involving Google's Imagen for image
   generation, Google's Veo for video creation, Google's Chirp 3 HD for realistic
   voices, or Google's Lyria for music composition, allowing for dynamic content
   creation within AI applications.
●​ External API Interaction: MCP provides a standardized way for LLMs to call and
   receive responses from any external API. This means an agent can fetch live
   weather data, pull stock prices, send emails, or interact with CRM systems,
   extending its capabilities far beyond its core language model.
●​ Reasoning-Based Information Extraction: Leveraging an LLM's strong
   reasoning skills, MCP facilitates effective, query-dependent information
   extraction that surpasses conventional search and retrieval systems. Instead of a
                                                                                       6

   traditional search tool returning an entire document, an agent can analyze the
   text and extract the precise clause, figure, or statement that directly answers a
   user's complex question.
●​ Custom Tool Development: Developers can build custom tools and expose them
   via an MCP server (e.g., using FastMCP). This allows specialized internal functions
   or proprietary systems to be made available to LLMs and other agents in a
   standardized, easily consumable format, without needing to modify the LLM
   directly.
●​ Standardized LLM-to-Application Communication: MCP ensures a consistent
   communication layer between LLMs and the applications they interact with. This
   reduces integration overhead, promotes interoperability between different LLM
   providers and host applications, and simplifies the development of complex
   agentic systems.
●​ Complex Workflow Orchestration: By combining various MCP-exposed tools
   and data sources, agents can orchestrate highly complex, multi-step workflows.
   An agent could, for example, retrieve customer data from a database, generate a
   personalized marketing image, draft a tailored email, and then send it, all by
   interacting with different MCP services.
●​ IoT Device Control: MCP can facilitate LLM interaction with Internet of Things
   (IoT) devices. An agent could use MCP to send commands to smart home
   appliances, industrial sensors, or robotics, enabling natural language control and
   automation of physical systems.
●​ Financial Services Automation: In financial services, MCP could enable LLMs to
   interact with various financial data sources, trading platforms, or compliance
   systems. An agent might analyze market data, execute trades, generate
   personalized financial advice, or automate regulatory reporting, all while
   maintaining secure and standardized communication.
In short, the Model Context Protocol (MCP) enables agents to access real-time
information from databases, APIs, and web resources. It also allows agents to perform
actions like sending emails, updating records, controlling devices, and executing
complex tasks by integrating and processing data from various sources. Additionally,
MCP supports media generation tools for AI applications.


Hands-On Code Example with ADK
This section outlines how to connect to a local MCP server that provides file system
operations, enabling an ADK agent to interact with the local file system.



                                                                                       7

Agent Setup with MCPToolset
To configure an agent for file system interaction, an `agent.py` file must be created
(e.g., at `./adk_agent_samples/mcp_agent/agent.py`). The `MCPToolset` is
instantiated within the `tools` list of the `LlmAgent` object. It is crucial to replace
`"/path/to/your/folder"` in the `args` list with the absolute path to a directory on the
local system that the MCP server can access. This directory will be the root for the file
system operations performed by the agent.


 import os
 from google.adk.agents import LlmAgent
 from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset,
 StdioServerParameters

 # Create a reliable absolute path to a folder named
 'mcp_managed_files'
 # within the same directory as this agent script.
 # This ensures the agent works out-of-the-box for demonstration.
 # For production, you would point this to a more persistent and
 secure location.
 TARGET_FOLDER_PATH =
 os.path.join(os.path.dirname(os.path.abspath(__file__)),
 "mcp_managed_files")

 # Ensure the target directory exists before the agent needs it.
 os.makedirs(TARGET_FOLDER_PATH, exist_ok=True)

 root_agent = LlmAgent(
    model='gemini-2.0-flash',
    name='filesystem_assistant_agent',
    instruction=(
        'Help the user manage their files. You can list files, read
 files, and write files. '
        f'You are operating in the following directory:
 {TARGET_FOLDER_PATH}'
    ),
    tools=[
        MCPToolset(
            connection_params=StdioServerParameters(
                command='npx',
                args=[
                    "-y", # Argument for npx to auto-confirm install
                    "@modelcontextprotocol/server-filesystem",
                    # This MUST be an absolute path to a folder.

                                                                                        8

                        TARGET_FOLDER_PATH,
                   ],
            ),
            # Optional: You can filter which tools from the MCP server
 are exposed.
            # For example, to only allow reading:
            # tool_filter=['list_directory', 'read_file']
        )
    ],
 )



`npx` (Node Package Execute), bundled with npm (Node Package Manager) versions
5.2.0 and later, is a utility that enables direct execution of Node.js packages from the
npm registry. This eliminates the need for global installation. In essence, `npx` serves
as an npm package runner, and it is commonly used to run many community MCP
servers, which are distributed as Node.js packages.

Creating an __init__.py file is necessary to ensure the agent.py file is recognized as
part of a discoverable Python package for the Agent Development Kit (ADK). This file
should reside in the same directory as agent.py.



 # ./adk_agent_samples/mcp_agent/__init__.py
 from . import agent


Certainly, other supported commands are available for use. For example, connecting
to python3 can be achieved as follows:


 connection_params = StdioConnectionParams(
  server_params={
      "command": "python3",
      "args": ["./agent/mcp_server.py"],
      "env": {
        "SERVICE_ACCOUNT_PATH":SERVICE_ACCOUNT_PATH,
        "DRIVE_FOLDER_ID": DRIVE_FOLDER_ID
      }
  }
 )




                                                                                           9

UVX, in the context of Python, refers to a command-line tool that utilizes uv to execute
commands in a temporary, isolated Python environment. Essentially, it allows you to
run Python tools and packages without needing to install them globally or within your
project's environment. You can run it via the MCP server.


connection_params = StdioConnectionParams(
 server_params={
   "command": "uvx",
   "args": ["mcp-google-sheets@latest"],
   "env": {
     "SERVICE_ACCOUNT_PATH":SERVICE_ACCOUNT_PATH,
     "DRIVE_FOLDER_ID": DRIVE_FOLDER_ID
   }
 }
)


Once the MCP Server is created, the next step is to connect to it.


Connecting the MCP Server with ADK Web
To begin, execute 'adk web'. Navigate to the parent directory of mcp_agent (e.g.,
adk_agent_samples) in your terminal and run:


cd ./adk_agent_samples # Or your equivalent parent directory
adk web


Once the ADK Web UI has loaded in your browser, select the
`filesystem_assistant_agent` from the agent menu. Next, experiment with prompts
such as:

   ●​ "Show me the contents of this folder."
   ●​ "Read the `sample.txt` file." (This assumes `sample.txt` is located at
      `TARGET_FOLDER_PATH`.)
   ●​ "What's in `another_file.md`?"




                                                                                     10

Creating an MCP Server with FastMCP
FastMCP is a high-level Python framework designed to streamline the development of
MCP servers. It provides an abstraction layer that simplifies protocol complexities,
allowing developers to focus on core logic.

The library enables rapid definition of tools, resources, and prompts using simple
Python decorators. A significant advantage is its automatic schema generation, which
intelligently interprets Python function signatures, type hints, and documentation
strings to construct necessary AI model interface specifications. This automation
minimizes manual configuration and reduces human error.

Beyond basic tool creation, FastMCP facilitates advanced architectural patterns like
server composition and proxying. This enables modular development of complex,
multi-component systems and seamless integration of existing services into an
AI-accessible framework. Additionally, FastMCP includes optimizations for efficient,
distributed, and scalable AI-driven applications.


Server setup with FastMCP
To illustrate, consider a basic "greet" tool provided by the server. ADK agents and
other MCP clients can interact with this tool using HTTP once it is active.

# fastmcp_server.py
# This script demonstrates how to create a simple MCP server using FastMCP.
# It exposes a single tool that generates a greeting.

# 1. Make sure you have FastMCP installed:
# pip install fastmcp
from fastmcp import FastMCP, Client

# Initialize the FastMCP server.
mcp_server = FastMCP()

# Define a simple tool function.
# The `@mcp_server.tool` decorator registers this Python function as an MCP
tool.
# The docstring becomes the tool's description for the LLM.
@mcp_server.tool
def greet(name: str) -> str:
    """
    Generates a personalized greeting.

     Args:


                                                                                       11

          name: The name of the person to greet.

     Returns:
         A greeting string.
     """
     return f"Hello, {name}! Nice to meet you."

# Or if you want to run it from the script:
if __name__ == "__main__":
    mcp_server.run(
        transport="http",
        host="127.0.0.1",
