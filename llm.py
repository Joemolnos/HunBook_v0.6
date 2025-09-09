from config import groq_client
from stats import GenerationStatistics


def generate_book_structure(prompt: str):
    completion = groq_client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[
            {"role": "system", "content": "Write in JSON format:\n\n{\"Title of section goes here\":\"Description of section goes here\",\n\"Title of section goes here\":{\"Title of section goes here\":\"Description of section goes here\",\"Title of section goes here\":\"Description of section goes here\",\"Title of section goes here\":\"Description of section goes here\"}}"},
            {"role": "user", "content": f"Write a comprehensive structure, omiting introduction and conclusion sections (forward, author's note, summary), for a long (>300 page) book on the following subject:\n\n<subject>{prompt}</subject>"}
        ],
        temperature=0.3,
        max_tokens=8000,
        top_p=1,
        stream=False,
        response_format={"type": "json_object"},
        stop=None,
    )

    usage = completion.usage
    statistics = GenerationStatistics(input_time=usage.prompt_time, output_time=usage.completion_time, input_tokens=usage.prompt_tokens, output_tokens=usage.completion_tokens, total_time=usage.total_time, model_name="openai/gpt-oss-120b")

    return statistics, completion.choices[0].message.content


def generate_section(prompt: str):
    stream = groq_client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=[
            {"role": "system", "content": "You are an expert writer. Generate a long, comprehensive, structured chapter for the section provided."},
            {"role": "user", "content": f"Generate a long, comprehensive, structured chapter for the following section:\n\n<section_title>{prompt}</section_title>"}
        ],
        temperature=0.3,
        max_tokens=8000,
        top_p=1,
        stream=True,
        stop=None,
    )

    for chunk in stream:
        # Yield text tokens as they arrive
        try:
            tokens = chunk.choices[0].delta.content
        except Exception:
            tokens = None
        if tokens:
            yield tokens

        # Handle Groq usage metadata on the final chunk (dict or object)
        xg = getattr(chunk, "x_groq", None)
        if not xg:
            continue
        usage = xg.get("usage") if isinstance(xg, dict) else getattr(xg, "usage", None)
        if not usage:
            continue
        get_val = usage.get if isinstance(usage, dict) else (lambda k, d=None: getattr(usage, k, d))
        statistics = GenerationStatistics(
            input_time=get_val("prompt_time", 0),
            output_time=get_val("completion_time", 0),
            input_tokens=get_val("prompt_tokens", 0),
            output_tokens=get_val("completion_tokens", 0),
            total_time=get_val("total_time", 0),
            model_name="openai/gpt-oss-20b",
        )
        yield statistics
