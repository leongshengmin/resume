import pandas as pd
import graphviz as graphviz

edu = [
    [
        "B.COMP Computer Science (Awarded NUS Undergraduate Merit Scholarship)",
        "2017-2021",
        "National University of Singapore",
    ],
    ["-", "2019-2020", "NUS Overseas Colleges (Silicon Valley)"],
]
career = [
    [
        "Aug 2021 - Present",
        "Grab (Singapore)",
        "Senior Software Engineer (Observability Team)",
        """
PIC for Grab’s logging stack – Manage >1PiB Opensearch clusters and logging pipelines.
""",
    ],
    [
        "Jan 2021 - June 2021",
        "Shopee (Singapore)",
        "Backend Software Engineer Intern (Payments Team)",
        "Instrumented service with Prometheus metrics to trace performance bottlenecks.",
    ],
    [
        "Apr 2020 - Aug 2020",
        "Ninja Van (Singapore)",
        "Full Stack Software Engineer Intern (Drivers Team)",
        "Designed and built a 2-way cross-platform messaging system for communication during parcel delivery.",
    ],
    [
        "Aug 2019 - Mar 2020",
        "UpGuard (California, US)",
        "DevOps / SRE Intern",
        "Developed release package upload tool for Forward Deploy Engineers to install packages on customers' VMs.",
    ],
    [
        "May 2019 - Aug 2019",
        "Ninja Van (Singapore)",
        "Backend Software Engineer Intern (Shippers Team)",
        "Developed a webhook history tool to allow tracking and searching of fired webhooks.",
    ],
]

info = {
    "name": "Leong Shengmin",
    "Brief": "Currently a Senior Software Engineer (Observability) @ Grab with 3+ years of experience looking to learn more about platform engineering / anything interesting.",
    "Mobile": "+6581980550",
    "Email": "leongshengmin@gmail.com",
    "LinkedIn": "https://www.linkedin.com/in/leongshengmin/",
    "edu": pd.DataFrame(edu, columns=["Qualification", "Year", "Institute"]),
    "career": pd.DataFrame(career, columns=["Year", "Company", "Role", "Description"]),
    "skills_or_tech": [
        "Languages: Python / Java / Bash (scripting)",
        "Technologies: Elasticsearch / Kafka / Helm / K8S",
        "Misc: Experience with AWS > Azure > GCP",
    ],
    "projects": [
        {
            "title": "Opensearch Cold Tier using JuiceFS (FUSE backed storage)",
            "description": "Conducted trial using JuiceFs (FUSE) as the cold data tier in Grab's 1PiB+ Opensearch logging cluster as part of a cost-reduction initiative for lower cost storage.",
        },
        {
            "title": "Benchmarking alternative Storage Engines (e.g. Clickhouse, Quickwit, Loki)",
            "description": "Conducted benchmarking alternative storage engines e.g. Clickhouse, Quickwit and Loki as part of a cost-reduction initiative for Grab's logging cluster.",
        },
        {
            "title": "Rack Aware Kafka Producer (Logstash Plugin)",
            "description": "Developed a Rack Aware Kafka producer Logstash plugin (Java) to reduce cross-AZ costs between Kafka producer and Kafka",
        },
        {
            "title": "RCA Troubleshooting LLM Bot",
            "description": "Developed tool to automate investigation of common troubleshooting flows e.g. panics, Hystrix errors during an outage and present LLM summarized findings in a single Grafana dashboard. Aimed to help reduce context-switching between platforms and surface only relevant signals to prevent information-overload.",
        },
        {
            "title": "Azure Log Buffering Layer",
            "description": "Setup Eventhub buffer in Azure for backpressure to improve reliability of log delivery between Azure and AWS.",
        },
        {
            "title": "Clickhouse Backup",
            "description": "Created script to periodically backup Clickhouse cluster used for SLA Monitoring into S3.",
        },
        {
            "title": "Deploying Configuration over AWS Systems Manager (SSM)",
            "description": "Created flow to perform ansible-push over AWS SSM for canary testing / deploying configuration changes fleet-wide.",
        },
        {
            "title": "YPT Stop Human Trafficking Hackathon (Sacremento)",
            "description": "Achieved 1st in a Tech for Good hackathon which aimed to use transportation tech to solve human trafficking.",
        },
        {
            "title": "Developers’ Week Hackathon (San Francisco)",
            "description": "Developed and deployed a travel gamification app.",
        },
        {
            "title": "NASA Hackathon by WeSolve (San Francisco)",
            "description": "Developed an AR iOS mobile application to transform space into a virtual playground.",
        },
        {
            "title": "Container Vulnerability Enumeration (CVE) Scanner",
            "description": "Built tool to build, push and scan container images for vulnerabilities",
        },
    ],
}

SKILLS_NUM_COLUMNS = 1
