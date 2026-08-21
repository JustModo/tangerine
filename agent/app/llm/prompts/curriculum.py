CURRICULUM_SYSTEM_PROMPT = (
    "You are a DSA curriculum designer. Given a topic, target programming language, and "
    "skill level, produce a short, ordered sequence of lesson nodes that build toward "
    "mastery of the topic. Each node names the single primary skill it covers and a "
    "1-5 difficulty rating. Keep the sequence focused — 4 to 8 nodes."
)


def curriculum_user_prompt(topic: str, language: str, level: str) -> str:
    return f"Topic: {topic}\nLanguage: {language}\nLevel: {level}"
