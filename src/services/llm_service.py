"""
/**
 * @file llm_service.py
 * @summary Service wrapper for a local Ollama LLM used to generate answers and
 *          full Markdown news articles.
 *
 * @details
 * - Uses an httpx.AsyncClient with connection pooling for efficient local HTTP
 *   calls to the Ollama server.
 * - Exposes convenience methods for text generation, answering one of the
 *   seven required questions, and composing a full article.
 * - Records basic performance timings via the shared performance monitor.
 *
 * @dependencies
 * - httpx (async HTTP client)
 * - utils.schemas (BillData, prompts, and models)
 */
"""

import asyncio
import json
from typing import Dict, List, Optional, Any
import httpx
from utils.schemas import BillData, QuestionType, QUESTION_PROMPTS, GeneratedArticle


class LLMServiceError(Exception):
    """Custom exception for LLM service errors."""
    pass


class OllamaService:
    """
    /**
     * Service for interacting with a local Ollama instance.
     *
     * @param base_url: Base URL of the Ollama server (default localhost).
     * @param model: Model name/tag to use (e.g., "qwen2.5:7b").
     */
    """
    
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "qwen2.5:7b"):
        self.base_url = base_url
        self.model = model
        self.timeout = 60.0  # Reduced to 1 minute for faster failure detection
        # Create persistent HTTP client with connection pooling
        self._http_client = None
    
    async def _get_http_client(self):
        """
        /**
         * Get or create a persistent HTTP client with connection pooling.
         */
        """
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=self.timeout,
                limits=httpx.Limits(
                    max_connections=50,
                    max_keepalive_connections=20
                )
            )
        return self._http_client
    
    async def _make_request(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        /**
         * Make a POST request to the Ollama API.
         *
         * @param endpoint: Relative API path (e.g., "/api/generate").
         * @param data: JSON body to send to the endpoint.
         * @return Parsed JSON response.
         */
        """
        url = f"{self.base_url}{endpoint}"
        
        try:
            client = await self._get_http_client()
            response = await client.post(url, json=data)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            raise LLMServiceError(f"Ollama request failed: {e}")
        except httpx.HTTPStatusError as e:
            raise LLMServiceError(f"Ollama API error: {e.response.status_code} - {e.response.text}")
    
    async def generate_text(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """
        /**
         * Generate text using the configured local model.
         *
         * @param prompt: Primary content prompt.
         * @param system_prompt: Optional system guidance for style/tone.
         * @return Model response text.
         */
        """
        import time
        
        data = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.3,     # Lower for faster generation
                "top_p": 0.7,           # Reduced for speed
                "num_predict": 4096,     # Increased for full article generation
                "num_ctx": 2048,         # More context for better understanding
                "num_gpu": 1,            # Use GPU if available
                "num_thread": 16,        # Increased threads for faster processing
                "repeat_penalty": 1.05,  # Slightly reduced for speed
                "top_k": 20,            # Reduced for faster token selection
                "stop": []  # No stop sequences to allow complete articles
            }
        }
        
        if system_prompt:
            data["system"] = system_prompt
        
        try:
            start_time = time.time()
            response = await self._make_request("/api/generate", data)
            duration = time.time() - start_time
            
            # Record performance metrics
            try:
                from utils.performance_monitor import get_monitor
                await get_monitor().record_llm_call(duration)
            except:
                pass
            
            return response.get("response", "").strip()
        except Exception as e:
            raise LLMServiceError(f"Text generation failed: {e}")
    
    def _format_bill_data_for_prompt(self, bill_data: BillData) -> str:
        """
        /**
         * Produce a compact, human-readable summary of bill data for prompts.
         */
        """
        data_str = f"Bill: {bill_data.bill_id} - {bill_data.title}\n"
        data_str += f"Status: {bill_data.status or 'N/A'}\n"
        
        if bill_data.sponsor:
            data_str += f"Sponsor: {bill_data.sponsor.get('full_name', 'N/A')} ({bill_data.sponsor.get('party', 'N/A')}-{bill_data.sponsor.get('state', 'N/A')})\n"
        
        if bill_data.cosponsors:
            data_str += f"Cosponsors: {len(bill_data.cosponsors)} total\n"
        
        if bill_data.committees:
            data_str += f"Committees: {', '.join([c.get('name', 'N/A') for c in bill_data.committees[:2]])}\n"
        
        return data_str
    
    async def answer_question(self, bill_data: BillData, question_id: int) -> str:
        """
        /**
         * Answer one of the seven required questions for a bill.
         *
         * @param bill_data: Structured bill details.
         * @param question_id: Identifier from 1 to 7.
         * @return Markdown-formatted answer including hyperlinks where relevant.
         */
        """
        if question_id not in QUESTION_PROMPTS:
            raise ValueError(f"Invalid question ID: {question_id}")
        
        prompt = QUESTION_PROMPTS[question_id]
        bill_data_str = self._format_bill_data_for_prompt(bill_data)
        
        system_prompt = """You are a knowledgeable assistant that answers questions about U.S. congressional bills using only the provided data from Congress.gov. 

Instructions:
1. Use ONLY the information provided in the bill data
2. Be factual and accurate
3. Include proper hyperlinks in the format [text](url) where URLs are available
4. If information is not available, clearly state that
5. Be concise but comprehensive
6. Focus on the specific question being asked
"""
        
        full_prompt = f"""
{bill_data_str}

{prompt}

Answer:
"""
        
        try:
            answer = await self.generate_text(full_prompt, system_prompt)
            return answer
        except Exception as e:
            raise LLMServiceError(f"Failed to answer question {question_id} for {bill_data.bill_id}: {e}")
    
    async def generate_article(self, bill_data: BillData, question_answers: Dict[int, str], link_check_results: Dict[str, Any] = None) -> str:
        """
        /**
         * Generate a complete Markdown news article using bill data and the
         * previously generated question answers.
         *
         * @param bill_data: Structured bill information.
         * @param question_answers: Map of question_id -> answer text.
         * @param link_check_results: Optional link validation summary.
         * @return Markdown news article.
         */
        """
        
        # Format question answers
        answers_text = ""
        question_titles = {
            1: "What does this bill do?",
            2: "What committees is this bill in?",
            3: "Who is the sponsor?",
            4: "Who cosponsored this bill?",
            5: "Have any hearings happened?",
            6: "Have any amendments been proposed?",
            7: "Have any votes happened?"
        }
        
        for q_id, answer in question_answers.items():
            if q_id in question_titles:
                answers_text += f"**{question_titles[q_id]}**\n{answer}\n\n"
        
        # Add link validation context if available
        link_context = ""
        if link_check_results:
            valid_count = link_check_results.get('valid_count', 0)
            invalid_count = link_check_results.get('invalid_count', 0)
            link_context = f"""
Link Validation Results:
- Valid URLs: {valid_count}
- Invalid URLs: {invalid_count}
Note: Only use URLs that have been validated as working.
"""
        
        system_prompt = """You are a professional journalist writing news articles about U.S. congressional bills. 

Instructions:
1. Write a clear, engaging news article in Markdown format
2. Use the provided bill data and question answers as your source
3. Include proper hyperlinks in the format [text](url) to Congress.gov pages
4. Structure the article with appropriate headings
5. Make it sound like a real news brief
6. Be factual and objective
7. Include relevant details about the bill's progress and key players
8. Keep the article concise but informative (300-500 words)
9. Only include links that are verified to be working
"""
        
        prompt = f"""
Bill Data:
{self._format_bill_data_for_prompt(bill_data)}

Question Answers:
{answers_text}
{link_context}
Generate a news article about this bill:
"""
        
        try:
            article = await self.generate_text(prompt, system_prompt)
            return article
        except Exception as e:
            raise LLMServiceError(f"Failed to generate article for {bill_data.bill_id}: {e}")
    
    async def check_model_availability(self) -> bool:
        """
        /**
         * Verify that the target model is available locally.
         */
        """
        try:
            response = await self._make_request("/api/tags", {})
            models = [model.get("name", "") for model in response.get("models", [])]
            return self.model in models
        except Exception:
            return False
    
    async def pull_model(self) -> bool:
        """
        /**
         * Attempt to pull the model if it is not already present.
         */
        """
        try:
            data = {"name": self.model, "stream": False}
            await self._make_request("/api/pull", data)
            return True
        except Exception as e:
            print(f"Failed to pull model {self.model}: {e}")
            return False


# Example usage and testing
async def main():
    """Test the Ollama service."""
    service = OllamaService()
    
    # Check if model is available
    if not await service.check_model_availability():
        print(f"Model {service.model} not found. Attempting to pull...")
        if not await service.pull_model():
            print("Failed to pull model")
            return
    
    # Test text generation
    try:
        response = await service.generate_text("What is the capital of France?")
        print(f"Generated: {response}")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
