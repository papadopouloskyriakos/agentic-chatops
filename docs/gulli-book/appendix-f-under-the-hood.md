# Appendix F: Under the Hood — An Inside Look at the Agents' Reasoning Engines (header may be fused with Appendix G in the PDF extract)

> From *Agentic Design Patterns — A Hands-On Guide to Building Intelligent Systems* by Antonio Gulli.
> Source: [`docs/Agentic_Design_Patterns.pdf`](../Agentic_Design_Patterns.pdf) (extracted 2026-04-23 via `pdftotext -layout`).
> Overview: [`docs/gulli-book-overview.md`](../gulli-book-overview.md).
> Our platform's status on this pattern: see [`wiki/patterns/`](../../wiki/patterns/).

---

Haystack: Haystack is an open-source framework engineered for building scalable and
production-ready search systems powered by language models. Its architecture is
composed of modular, interoperable nodes that form pipelines for document retrieval,
question answering, and summarization. The main strength of Haystack is its focus on
performance and scalability for large-scale information retrieval tasks, making it suitable
for enterprise-grade applications. A potential trade-off is that its design, optimized for
search pipelines, can be more rigid for implementing highly dynamic and creative
agentic behaviors.




                                                                                          6

MetaGPT: MetaGPT implements a multi-agent system by assigning roles and tasks
based on a predefined set of Standard Operating Procedures (SOPs). This framework
structures agent collaboration to mimic a software development company, with agents
taking on roles like product managers or engineers to complete complex tasks. This
SOP-driven approach results in highly structured and coherent outputs, which is a
significant advantage for specialized domains like code generation. The framework's
primary limitation is its high degree of specialization, making it less adaptable for
general-purpose agentic tasks outside of its core design.

SuperAGI: SuperAGI is an open-source framework designed to provide a complete
lifecycle management system for autonomous agents. It includes features for agent
provisioning, monitoring, and a graphical interface, aiming to enhance the reliability of
agent execution. The key benefit is its focus on production-readiness, with built-in
mechanisms to handle common failure modes like looping and to provide observability
into agent performance. A potential drawback is that its comprehensive platform
approach can introduce more complexity and overhead than a more lightweight,
library-based framework.

Semantic Kernel: Developed by Microsoft, Semantic Kernel is an SDK that integrates
large language models with conventional programming code through a system of
"plugins" and "planners." It allows an LLM to invoke native functions and orchestrate
workflows, effectively treating the model as a reasoning engine within a larger software
application. Its primary strength is its seamless integration with existing enterprise
codebases, particularly in .NET and Python environments. The conceptual overhead of
its plugin and planner architecture can present a steeper learning curve compared to
more straightforward agent frameworks.

Strands Agents: An AWS lightweight and flexible SDK that uses a model-driven
approach for building and running AI agents. It is designed to be simple and scalable,
supporting everything from basic conversational assistants to complex multi-agent
autonomous systems. The framework is model-agnostic, offering broad support for
various LLM providers, and includes native integration with the MCP for easy access to
external tools. Its core advantage is its simplicity and flexibility, with a customizable
agent loop that is easy to get started with. A potential trade-off is that its lightweight
design means developers may need to build out more of the surrounding operational
infrastructure, such as advanced monitoring or lifecycle management systems, which
more comprehensive frameworks might provide out-of-the-box.

Conclusion


                                                                                             7

The landscape of agentic frameworks offers a diverse spectrum of tools, from low-level
libraries for defining agent logic to high-level platforms for orchestrating multi-agent
collaboration. At the foundational level, LangChain enables simple, linear workflows,
while LangGraph introduces stateful, cyclical graphs for more complex reasoning.
Higher-level frameworks like CrewAI and Google's ADK shift the focus to orchestrating
teams of agents with predefined roles, while others like LlamaIndex specialize in
data-intensive applications. This variety presents developers with a core trade-off
between the granular control of graph-based systems and the streamlined development
of more opinionated platforms. Consequently, selecting the right framework hinges on
whether the application requires a simple sequence, a dynamic reasoning loop, or a
managed team of specialists. Ultimately, this evolving ecosystem empowers developers
to build increasingly sophisticated AI systems by choosing the precise level of
abstraction their project demands.

References
   1.​ LangChain, https://www.langchain.com/
   2.​ LangGraph, https://www.langchain.com/langgraph
   3.​ Google's ADK, https://google.github.io/adk-docs/
   4.​ Crew.AI, https://docs.crewai.com/en/introduction




                                                                                       8

Appendix D - Building an Agent with
AgentSpace
Overview
AgentSpace is a platform designed to facilitate an "agent-driven enterprise" by
integrating artificial intelligence into daily workflows. At its core, it provides a unified
search capability across an organization's entire digital footprint, including documents,
emails, and databases. This system utilizes advanced AI models, like Google's Gemini,
to comprehend and synthesize information from these varied sources.

The platform enables the creation and deployment of specialized AI "agents" that can
perform complex tasks and automate processes. These agents are not merely chatbots;
they can reason, plan, and execute multi-step actions autonomously. For instance, an
agent could research a topic, compile a report with citations, and even generate an
audio summary.

To achieve this, AgentSpace constructs an enterprise knowledge graph, mapping the
relationships between people, documents, and data. This allows the AI to understand
context and deliver more relevant and personalized results. The platform also includes a
no-code interface called Agent Designer for creating custom agents without requiring
deep technical expertise.

Furthermore, AgentSpace supports a multi-agent system where different AI agents can
communicate and collaborate through an open protocol known as the Agent2Agent
(A2A) Protocol. This interoperability allows for more complex and orchestrated
workflows. Security is a foundational component, with features like role-based access
controls and data encryption to protect sensitive enterprise information. Ultimately,
AgentSpace aims to enhance productivity and decision-making by embedding
intelligent, autonomous systems directly into an organization's operational fabric.


How to build an Agent with AgentSpace UI
Figure 1 illustrates how to access AgentSpace by selecting AI Applications from the Google
Cloud Console.




                                                                                             1

              Fig. 1: How to use Google Cloud Console to access AgentSpace

Your agent can be connected to various services, including Calendar, Google Mail,
Workaday, Jira, Outlook, and Service Now (see Fig. 2).




      Fig. 2: Integrate with diverse services, including Google and third-party platforms.



                                                                                             2

The Agent can then utilize its own prompt, chosen from a gallery of pre-made prompts
provided by Google, as illustrated in Fig. 3.




                     Fig.3: Google's Gallery of Pre-assembled prompts

In alternative you can create your own prompt as in Fig.4, which will be then used by
your agent




                                                                                        3

                         Fig.4: Customizing the Agent's Prompt

AgentSpace offers a number of advanced features such as integration with datastores
to store your own data, integration with Google Knowledge Graph or with your private
Knowledge Graph, Web interface for exposing your agent to the Web, and Analytics to
monitor usage, and more (see Fig. 5)




                                                                                  4

                          Fig. 5: AgentSpace advanced capabilities



Upon completion, the AgentSpace chat interface (Fig. 6) will be accessible.




          Fig. 6: The AgentSpace User Interface for initiating a chat with your Agent.




                                                                                         5

Conclusion
In conclusion, AgentSpace provides a functional framework for developing and
deploying AI agents within an organization's existing digital infrastructure. The system's
architecture links complex backend processes, such as autonomous reasoning and
enterprise knowledge graph mapping, to a graphical user interface for agent
construction. Through this interface, users can configure agents by integrating various
data services and defining their operational parameters via prompts, resulting in
customized, context-aware automated systems.

This approach abstracts the underlying technical complexity, enabling the construction
of specialized multi-agent systems without requiring deep programming expertise. The
primary objective is to embed automated analytical and operational capabilities directly
into workflows, thereby increasing process efficiency and enhancing data-driven
analysis. For practical instruction, hands-on learning modules are available, such as the
"Build a Gen AI Agent with Agentspace" lab on Google Cloud Skills Boost, which
provides a structured environment for skill acquisition.


References
   1.​ Create a no-code agent with Agent Designer,
       https://cloud.google.com/agentspace/agentspace-enterprise/docs/agent-designer
   2.​ Google Cloud Skills Boost, https://www.cloudskillsboost.google/




                                                                                         6

Appendix E - AI Agents on the CLI
Introduction
​The developer's command line, long a bastion of precise, imperative commands, is
 undergoing a profound transformation. It is evolving from a simple shell into an
 intelligent, collaborative workspace powered by a new class of tools: AI Agent
 Command-Line Interfaces (CLIs). These agents move beyond merely executing
 commands; they understand natural language, maintain context about your entire
 codebase, and can perform complex, multi-step tasks that automate significant parts of
 the development lifecycle.

This guide provides an in-depth look at four leading players in this burgeoning field,
exploring their unique strengths, ideal use cases, and distinct philosophies to help you
determine which tool best fits your workflow. It is important to note that many of the
