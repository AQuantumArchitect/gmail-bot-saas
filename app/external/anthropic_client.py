# app/external/anthropic_client.py
"""
Anthropic AI Client - External service integration for Claude API operations.
Provides email summarization, content analysis, and AI processing with proper error handling.
"""
import logging
import time
import json
from typing import Dict, Any, List, Optional, Union
from datetime import datetime, timedelta
import httpx

from app.core.config import settings
from app.core.exceptions import APIError, ValidationError, AuthenticationError

logger = logging.getLogger(__name__)


class AnthropicClient:
    """
    Anthropic Claude API client with retry logic, rate limiting, and content processing.
    Handles email summarization, content analysis, and AI operations.
    """
    
    # Anthropic API configuration
    API_BASE = "https://api.anthropic.com"
    API_VERSION = "2023-06-01"
    
    # Model configurations
    MODELS = {
        "claude-3-haiku": {
            "name": "claude-3-haiku-20240307",
            "context_length": 200000,
            "cost_per_token": 0.00000025,  # $0.25 per 1M tokens
            "max_tokens": 4096,
            "best_for": "fast, lightweight summaries"
        },
        "claude-3-sonnet": {
            "name": "claude-3-sonnet-20240229",
            "context_length": 200000,
            "cost_per_token": 0.000003,    # $3 per 1M tokens
            "max_tokens": 4096,
            "best_for": "balanced quality and speed"
        },
        "claude-3-opus": {
            "name": "claude-3-opus-20240229",
            "context_length": 200000,
            "cost_per_token": 0.000015,    # $15 per 1M tokens
            "max_tokens": 4096,
            "best_for": "highest quality analysis"
        }
    }
    
    # Rate limiting (Anthropic's limits)
    MAX_REQUESTS_PER_MINUTE = 1000
    MAX_TOKENS_PER_MINUTE = 40000
    
    def __init__(self, default_model: str = "claude-3-haiku"):
        self.api_key = settings.anthropic_api_key
        self.default_model = default_model
        
        # Rate limiting state
        self._request_times = []
        self._token_usage = []
        self._last_request_time = 0
        
        # Circuit breaker state
        self._circuit_breaker = {
            "failure_count": 0,
            "last_failure": None,
            "state": "closed"  # closed, open, half-open
        }
        
        # Cost tracking
        self._total_cost = 0.0
        self._total_tokens = 0
    
    # --- Email Summarization ---
    
    async def generate_email_summary(
        self,
        email_content: str,
        email_metadata: Optional[Dict[str, Any]] = None,
        summary_style: str = "concise",
        max_length: int = 200
    ) -> Dict[str, Any]:
        """
        Generate AI summary of email content.
        
        Args:
            email_content: Email content to summarize
            email_metadata: Optional metadata (subject, sender, etc.)
            summary_style: Style of summary ("concise", "detailed", "bullet_points")
            max_length: Maximum summary length in words
            
        Returns:
            Summary result with text, key points, action items, and metadata
        """
        if not email_content or not email_content.strip():
            raise ValidationError("Email content cannot be empty")
        
        # Prepare email data
        email_data = {
            "content": email_content,
            "subject": email_metadata.get("subject", "") if email_metadata else "",
            "sender": email_metadata.get("sender", "") if email_metadata else "",
            "recipient": email_metadata.get("recipient", "") if email_metadata else "",
            "date": email_metadata.get("date", "") if email_metadata else ""
        }
        
        # Create summary prompt
        prompt = self._create_summary_prompt(email_data, summary_style, max_length)
        
        # Generate summary
        response = await self._make_completion_request(
            prompt=prompt,
            max_tokens=min(max_length * 2, 1000),  # Estimate tokens needed
            temperature=0.3,
            model=self.default_model
        )
        
        # Parse response
        summary_data = self._parse_summary_response(response)
        
        logger.info(f"Generated email summary ({len(summary_data['summary'])} chars)")
        return summary_data
    
    def _create_summary_prompt(
        self,
        email_data: Dict[str, Any],
        style: str,
        max_length: int
    ) -> str:
        """Create prompt for email summarization."""
        
        style_instructions = {
            "concise": f"Write a brief, {max_length}-word summary focusing on key information.",
            "detailed": f"Write a comprehensive {max_length}-word summary with context and details.",
            "bullet_points": f"Create {max_length}-word summary using bullet points for clarity."
        }
        
        prompt = f"""
Please analyze this email and provide a summary in {style} style.

Email Details:
- Subject: {email_data['subject']}
- From: {email_data['sender']}
- To: {email_data['recipient']}
- Date: {email_data['date']}

Email Content:
{email_data['content']}

Instructions:
{style_instructions.get(style, style_instructions['concise'])}

Please provide your response in JSON format with the following structure:
{{
    "summary": "Your summary here",
    "key_points": ["point 1", "point 2", "point 3"],
    "action_items": ["action 1", "action 2"],
    "urgency_level": "low|medium|high|urgent",
    "sentiment": "positive|negative|neutral",
    "category": "work|personal|promotional|notification|other",
    "confidence_score": 0.95
}}

Ensure the summary is exactly within the {max_length} word limit.
"""
        return prompt.strip()
    
    def _parse_summary_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """Parse Claude's summary response."""
        content = response.get("content", [{}])[0].get("text", "")
        
        try:
            # Try to parse as JSON
            if content.strip().startswith("{"):
                summary_data = json.loads(content)
            else:
                # Fallback parsing if not JSON
                summary_data = {
                    "summary": content[:500],  # Truncate if too long
                    "key_points": [],
                    "action_items": [],
                    "urgency_level": "medium",
                    "sentiment": "neutral",
                    "category": "other",
                    "confidence_score": 0.8
                }
        except json.JSONDecodeError:
            # Fallback for non-JSON responses
            summary_data = {
                "summary": content[:500],
                "key_points": [],
                "action_items": [],
                "urgency_level": "medium",
                "sentiment": "neutral",
                "category": "other",
                "confidence_score": 0.7
            }
        
        # Add processing metadata
        summary_data.update({
            "processing_time": response.get("processing_time", 0),
            "tokens_used": response.get("usage", {}).get("total_tokens", 0),
            "cost_usd": response.get("cost_usd", 0.0),
            "model_used": response.get("model", self.default_model),
            "processed_at": datetime.utcnow().isoformat()
        })
        
        return summary_data
    
    # --- Batch Processing ---
    
    async def process_email_batch(
        self,
        emails: List[Dict[str, Any]],
        batch_size: int = 5,
        summary_style: str = "concise"
    ) -> List[Dict[str, Any]]:
        """
        Process multiple emails in batches.
        
        Args:
            emails: List of email data to process
            batch_size: Number of emails to process simultaneously
            summary_style: Summary style to use
            
        Returns:
            List of summary results
        """
        if not emails:
            return []
        
        results = []
        
        # Process in batches to avoid rate limits
        for i in range(0, len(emails), batch_size):
            batch = emails[i:i + batch_size]
            
            # Process batch
            batch_results = await self._process_batch(batch, summary_style)
            results.extend(batch_results)
            
            # Small delay between batches
            if i + batch_size < len(emails):
                await asyncio.sleep(1)
        
        logger.info(f"Processed {len(results)} emails in batches")
        return results
    
    async def _process_batch(
        self,
        batch: List[Dict[str, Any]],
        summary_style: str
    ) -> List[Dict[str, Any]]:
        """Process a single batch of emails."""
        import asyncio
        
        tasks = []
        for email in batch:
            task = self.generate_email_summary(
                email_content=email.get("content", ""),
                email_metadata=email,
                summary_style=summary_style
            )
            tasks.append(task)
        
        # Execute batch concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Handle exceptions
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Failed to process email {i}: {result}")
                processed_results.append({
                    "error": str(result),
                    "email_id": batch[i].get("id", "unknown"),
                    "processed": False
                })
            else:
                processed_results.append(result)
        
        return processed_results
    
    # --- Content Analysis ---
    
    async def analyze_email_content(
        self,
        email_content: str,
        analysis_types: List[str] = None
    ) -> Dict[str, Any]:
        """
        Perform detailed content analysis on email.
        
        Args:
            email_content: Email content to analyze
            analysis_types: Types of analysis to perform
            
        Returns:
            Analysis results
        """
        if not email_content:
            raise ValidationError("Email content cannot be empty")
        
        analysis_types = analysis_types or [
            "sentiment", "urgency", "category", "entities", "intent"
        ]
        
        prompt = self._create_analysis_prompt(email_content, analysis_types)
        
        response = await self._make_completion_request(
            prompt=prompt,
            max_tokens=1000,
            temperature=0.1,
            model=self.default_model
        )
        
        analysis_data = self._parse_analysis_response(response)
        
        logger.info(f"Analyzed email content ({len(analysis_types)} analysis types)")
        return analysis_data
    
    def _create_analysis_prompt(
        self,
        email_content: str,
        analysis_types: List[str]
    ) -> str:
        """Create prompt for email content analysis."""
        
        prompt = f"""
Please analyze this email content and provide insights:

Email Content:
{email_content}

Analysis Required:
{', '.join(analysis_types)}

Please provide your analysis in JSON format with the following structure:
{{
    "sentiment": {{"score": 0.8, "label": "positive|negative|neutral"}},
    "urgency": {{"score": 0.3, "label": "low|medium|high|urgent"}},
    "category": {{"label": "work|personal|promotional|notification|other", "confidence": 0.9}},
    "entities": [{{"text": "entity", "type": "person|organization|location|other"}}],
    "intent": {{"primary": "request|inform|schedule|other", "confidence": 0.8}},
    "key_topics": ["topic1", "topic2"],
    "language": "en",
    "professional_tone": true,
    "requires_response": true,
    "estimated_read_time": 30
}}

Provide detailed analysis based on the email content.
"""
        return prompt.strip()
    
    def _parse_analysis_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """Parse Claude's analysis response."""
        content = response.get("content", [{}])[0].get("text", "")
        
        try:
            if content.strip().startswith("{"):
                analysis_data = json.loads(content)
            else:
                # Fallback analysis
                analysis_data = {
                    "sentiment": {"score": 0.5, "label": "neutral"},
                    "urgency": {"score": 0.3, "label": "medium"},
                    "category": {"label": "other", "confidence": 0.5},
                    "entities": [],
                    "intent": {"primary": "inform", "confidence": 0.5},
                    "key_topics": [],
                    "language": "en",
                    "professional_tone": True,
                    "requires_response": False,
                    "estimated_read_time": 30
                }
        except json.JSONDecodeError:
            analysis_data = {
                "error": "Failed to parse analysis response",
                "raw_content": content[:200]
            }
        
        # Add processing metadata
        analysis_data.update({
            "processing_time": response.get("processing_time", 0),
            "tokens_used": response.get("usage", {}).get("total_tokens", 0),
            "cost_usd": response.get("cost_usd", 0.0),
            "model_used": response.get("model", self.default_model),
            "analyzed_at": datetime.utcnow().isoformat()
        })
        
        return analysis_data
    
    # --- Core API Operations ---
    
    async def _make_completion_request(
        self,
        prompt: str,
        max_tokens: int = 1000,
        temperature: float = 0.3,
        model: str = None
    ) -> Dict[str, Any]:
        """Make completion request to Anthropic API."""
        
        if not self.api_key:
            raise AuthenticationError("Anthropic API key not configured")
        
        # Check circuit breaker
        if not self._check_circuit_breaker():
            raise APIError("Circuit breaker is open - too many failures")
        
        # Apply rate limiting
        await self._apply_rate_limit(max_tokens)
        
        model_name = self.MODELS.get(model or self.default_model, {}).get("name", "claude-3-haiku-20240307")
        
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": self.API_VERSION
        }
        
        payload = {
            "model": model_name,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        }
        
        start_time = time.time()
        
        try:
            async with self._get_http_client() as client:
                response = await client.post(
                    f"{self.API_BASE}/v1/messages",
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()
                
                response_data = response.json()
                processing_time = time.time() - start_time
                
                # Track usage and cost
                usage = response_data.get("usage", {})
                total_tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
                cost = self._calculate_cost(total_tokens, model or self.default_model)
                
                self._record_usage(total_tokens, cost)
                self._record_success()
                
                # Add metadata to response
                response_data.update({
                    "processing_time": processing_time,
                    "cost_usd": cost,
                    "model": model_name
                })
                
                logger.info(f"Completed API request: {total_tokens} tokens, ${cost:.4f}")
                return response_data
                
        except httpx.HTTPStatusError as e:
            self._record_failure()
            if e.response.status_code == 401:
                raise AuthenticationError("Invalid Anthropic API key")
            elif e.response.status_code == 429:
                raise APIError("Rate limit exceeded")
            elif e.response.status_code == 400:
                error_data = e.response.json()
                raise ValidationError(f"API request error: {error_data.get('error', {}).get('message', str(e))}")
            raise APIError(f"Anthropic API error: {e}")
        except httpx.RequestError as e:
            self._record_failure()
            raise APIError(f"Network error: {e}")
    
    def _calculate_cost(self, total_tokens: int, model: str) -> float:
        """Calculate cost based on token usage and model."""
        model_config = self.MODELS.get(model, self.MODELS["claude-3-haiku"])
        cost_per_token = model_config["cost_per_token"]
        return total_tokens * cost_per_token
    
    def _record_usage(self, tokens: int, cost: float):
        """Record token usage and cost."""
        self._total_tokens += tokens
        self._total_cost += cost
        
        # Keep track of usage for rate limiting
        now = time.time()
        self._token_usage.append({"time": now, "tokens": tokens})
        
        # Remove old usage (older than 1 minute)
        self._token_usage = [
            usage for usage in self._token_usage 
            if now - usage["time"] < 60
        ]
    
    # --- Helper Methods ---
    
    def _get_http_client(self) -> httpx.AsyncClient:
        """Get HTTP client with proper configuration."""
        return httpx.AsyncClient(
            timeout=60.0,  # Longer timeout for AI processing
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20)
        )
    
    async def _apply_rate_limit(self, tokens_needed: int):
        """Apply rate limiting based on requests and tokens."""
        now = time.time()
        
        # Remove old requests and token usage
        self._request_times = [t for t in self._request_times if now - t < 60]
        self._token_usage = [u for u in self._token_usage if now - u["time"] < 60]
        
        # Check request rate limit
        if len(self._request_times) >= self.MAX_REQUESTS_PER_MINUTE:
            sleep_time = 60 - (now - self._request_times[0])
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
        
        # Check token rate limit
        current_tokens = sum(u["tokens"] for u in self._token_usage)
        if current_tokens + tokens_needed > self.MAX_TOKENS_PER_MINUTE:
            sleep_time = 60 - (now - self._token_usage[0]["time"])
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
        
        # Small delay between requests
        if now - self._last_request_time < 0.1:  # 100ms minimum between requests
            await asyncio.sleep(0.1)
        
        self._request_times.append(time.time())
        self._last_request_time = time.time()
    
    def _check_circuit_breaker(self) -> bool:
        """Check if circuit breaker allows requests."""
        now = datetime.utcnow()
        
        if self._circuit_breaker["state"] == "open":
            if (self._circuit_breaker["last_failure"] and 
                now - self._circuit_breaker["last_failure"] > timedelta(minutes=5)):
                self._circuit_breaker["state"] = "half-open"
                return True
            return False
        
        return True
    
    def _record_success(self):
        """Record successful API call."""
        self._circuit_breaker["failure_count"] = 0
        self._circuit_breaker["state"] = "closed"
    
    def _record_failure(self):
        """Record failed API call."""
        self._circuit_breaker["failure_count"] += 1
        self._circuit_breaker["last_failure"] = datetime.utcnow()
        
        if self._circuit_breaker["failure_count"] >= 3:
            self._circuit_breaker["state"] = "open"
            logger.warning("Anthropic API circuit breaker opened due to failures")
    
    # --- Utility Methods ---
    
    def get_usage_stats(self) -> Dict[str, Any]:
        """Get usage statistics."""
        return {
            "total_tokens": self._total_tokens,
            "total_cost_usd": self._total_cost,
            "requests_last_minute": len(self._request_times),
            "tokens_last_minute": sum(u["tokens"] for u in self._token_usage),
            "circuit_breaker_state": self._circuit_breaker["state"],
            "available_models": list(self.MODELS.keys())
        }
    
    def get_model_info(self, model: str = None) -> Dict[str, Any]:
        """Get information about a specific model."""
        model_key = model or self.default_model
        return self.MODELS.get(model_key, {})
    
    def estimate_cost(self, text: str, model: str = None) -> Dict[str, Any]:
        """Estimate cost for processing text."""
        # Simple token estimation (4 characters ≈ 1 token)
        estimated_tokens = len(text) // 4
        
        model_config = self.MODELS.get(model or self.default_model, self.MODELS["claude-3-haiku"])
        estimated_cost = estimated_tokens * model_config["cost_per_token"]
        
        return {
            "estimated_tokens": estimated_tokens,
            "estimated_cost_usd": estimated_cost,
            "model": model or self.default_model,
            "max_context_length": model_config["context_length"]
        }
    
    def validate_text_length(self, text: str, model: str = None) -> Dict[str, Any]:
        """Validate if text fits within model's context length."""
        model_config = self.MODELS.get(model or self.default_model, self.MODELS["claude-3-haiku"])
        
        # Simple token estimation
        estimated_tokens = len(text) // 4
        max_tokens = model_config["context_length"]
        
        return {
            "valid": estimated_tokens <= max_tokens,
            "estimated_tokens": estimated_tokens,
            "max_tokens": max_tokens,
            "utilization": estimated_tokens / max_tokens,
            "model": model or self.default_model
        }


# Import asyncio
import asyncio