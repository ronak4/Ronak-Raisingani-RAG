"""
/**
 * @file test_smoke.py
 * @summary Smoke tests for the RAG News Generation System that validate core
 *          behaviors without requiring full infrastructure.
 *
 * @details
 * - Verifies target bill lists, question types, and basic output structure.
 * - Checks JSON output schema, minimal content quality, and link formatting.
 * - Ensures critical components import and initialize correctly.
 */
"""

import pytest
import asyncio
import json
import os
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock

# Add src to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from utils.schemas import TARGET_BILLS, QuestionType, GeneratedArticle
from services.congress_api import CongressAPIClient
from services.state_manager import StateManager


class TestSmokeTests:
    """
    /**
     * Basic smoke tests that exercise schema and output expectations.
     */
    """
    
    def test_target_bills_defined(self):
        """
        /**
         * Verify the list of target bills contains ten expected identifiers.
         */
        """
        assert len(TARGET_BILLS) == 10
        assert "H.R.1" in TARGET_BILLS
        assert "S.2296" in TARGET_BILLS
        assert "S.RES.412" in TARGET_BILLS
        assert "H.RES.353" in TARGET_BILLS
    
    def test_question_types_defined(self):
        """
        /**
         * Verify all seven question types are present and correctly mapped.
         */
        """
        assert len(QuestionType) == 7
        assert QuestionType.WHAT_DOES_BILL_DO == 1
        assert QuestionType.WHAT_COMMITTEES == 2
        assert QuestionType.WHO_IS_SPONSOR == 3
        assert QuestionType.WHO_COSPONSORED == 4
        assert QuestionType.ANY_HEARINGS == 5
        assert QuestionType.ANY_AMENDMENTS == 6
        assert QuestionType.ANY_VOTES == 7
    
    def test_output_articles_exist(self):
        """
        /**
         * Ensure the articles output JSON exists and contains ten entries with
         * required fields present.
         */
        """
        output_path = Path(__file__).parent.parent / 'output' / 'articles.json'
        assert output_path.exists(), "Output articles file not found"
        
        with open(output_path, 'r') as f:
            articles = json.load(f)
        
        assert isinstance(articles, list), "Articles should be a list"
        assert len(articles) == 10, f"Expected 10 articles, got {len(articles)}"
        
        # Check first article structure
        first_article = articles[0]
        required_fields = ['bill_id', 'bill_title', 'sponsor_bioguide_id', 
                          'bill_committee_ids', 'article_content']
        for field in required_fields:
            assert field in first_article, f"Missing required field: {field}"
    
    def test_article_content_quality(self):
        """
        /**
         * Check that article content is present, contains markdown, and has
         * at least some hyperlinks or explicit Congress.gov references.
         */
        """
        output_path = Path(__file__).parent.parent / 'output' / 'articles.json'
        
        with open(output_path, 'r') as f:
            articles = json.load(f)
        
        for article in articles:
            # Check article has content
            assert article['article_content'], f"Article {article['bill_id']} has no content"
            assert len(article['article_content']) > 100, f"Article {article['bill_id']} too short"
            
            # Check for markdown formatting
            content = article['article_content']
            assert '##' in content or '**' in content, f"Article {article['bill_id']} lacks markdown formatting"
            
            # Check for hyperlinks (should have at least some) - be more lenient
            has_hyperlinks = '[' in content and '](' in content
            has_congress_links = 'congress.gov' in content.lower()
            assert has_hyperlinks or has_congress_links, f"Article {article['bill_id']} lacks hyperlinks or Congress.gov references"
    
    def test_bill_ids_valid(self):
        """
        /**
         * Validate that every bill_id in the output belongs to TARGET_BILLS.
         */
        """
        output_path = Path(__file__).parent.parent / 'output' / 'articles.json'
        
        with open(output_path, 'r') as f:
            articles = json.load(f)
        
        for article in articles:
            bill_id = article['bill_id']
            assert bill_id in TARGET_BILLS, f"Unexpected bill ID: {bill_id}"
    
    def test_schemas_valid(self):
        """
        /**
         * Validate basic types and optional fields for output articles.
         */
        """
        output_path = Path(__file__).parent.parent / 'output' / 'articles.json'
        
        with open(output_path, 'r') as f:
            articles = json.load(f)
        
        for article in articles:
            # Validate required fields
            assert isinstance(article['bill_id'], str)
            assert isinstance(article['bill_title'], str)
            assert isinstance(article['bill_committee_ids'], list)
            assert isinstance(article['article_content'], str)
            
            # Validate optional fields
            if article.get('sponsor_bioguide_id'):
                assert isinstance(article['sponsor_bioguide_id'], str)
            if article.get('word_count'):
                assert isinstance(article['word_count'], int)
            if article.get('link_count'):
                assert isinstance(article['link_count'], int)
    
    @pytest.mark.asyncio
    async def test_congress_api_client_initialization(self):
        """
        /**
         * Ensure the Congress API client initializes with expected defaults.
         */
        """
        client = CongressAPIClient()
        assert client.base_url == "https://api.congress.gov/v3"
        assert client.cache_dir.exists()
    
    @pytest.mark.asyncio
    async def test_state_manager_initialization(self):
        """
        /**
         * Ensure the State Manager can be constructed with a mocked Redis.
         */
        """
        # Mock Redis connection for testing
        with patch('redis.asyncio.from_url') as mock_redis:
            mock_redis.return_value = AsyncMock()
            state_manager = StateManager()
            assert state_manager is not None
    
    def test_requirements_file_exists(self):
        """
        /**
         * Confirm requirements.txt exists and includes key dependencies.
         */
        """
        req_path = Path(__file__).parent.parent / 'requirements.txt'
        assert req_path.exists(), "requirements.txt not found"
        
        with open(req_path, 'r') as f:
            requirements = f.read()
        
        # Check for key dependencies
        key_packages = ['kafka-python', 'redis', 'openai', 'httpx', 'pydantic']
        for package in key_packages:
            assert package in requirements, f"Missing required package: {package}"
    
    def test_docker_compose_exists(self):
        """
        /**
         * Confirm docker-compose.yml exists and includes required services.
         */
        """
        compose_path = Path(__file__).parent.parent / 'docker-compose.yml'
        assert compose_path.exists(), "docker-compose.yml not found"
        
        with open(compose_path, 'r') as f:
            compose_content = f.read()
        
        # Check for required services
        assert 'redpanda' in compose_content, "Redpanda service not found"
        assert 'redis' in compose_content, "Redis service not found"
    
    def test_dockerfile_exists(self):
        """
        /**
         * Confirm Dockerfile exists in the repository root.
         */
        """
        dockerfile_path = Path(__file__).parent.parent / 'Dockerfile'
        assert dockerfile_path.exists(), "Dockerfile not found"
    
    def test_cache_directory_structure(self):
        """
        /**
         * Verify cache directory exists and can contain JSON cache files.
         */
        """
        cache_path = Path(__file__).parent.parent / 'cache'
        assert cache_path.exists(), "Cache directory not found"
        
        # Check for some cached files
        cache_files = list(cache_path.glob('*.json'))
        if len(cache_files) > 0:
            # If cache files exist, verify they're valid JSON
            for cache_file in cache_files[:3]:  # Check first 3 files
                try:
                    with open(cache_file, 'r') as f:
                        json.load(f)
                except json.JSONDecodeError:
                    assert False, f"Invalid JSON in cache file: {cache_file.name}"
    
    def test_performance_metrics(self):
        """
        /**
         * If optional metrics exist in output, ensure they are sensible.
         */
        """
        output_path = Path(__file__).parent.parent / 'output' / 'articles.json'
        
        with open(output_path, 'r') as f:
            articles = json.load(f)
        
        # Check word counts are reasonable
        for article in articles:
            if 'word_count' in article:
                word_count = article['word_count']
                assert word_count > 50, f"Article {article['bill_id']} too short: {word_count} words"
                assert word_count < 2000, f"Article {article['bill_id']} too long: {word_count} words"
    
    def test_hyperlinks_valid_format(self):
        """
        /**
         * Validate markdown link formatting and HTTPS usage for Congress.gov.
         */
        """
        output_path = Path(__file__).parent.parent / 'output' / 'articles.json'
        
        with open(output_path, 'r') as f:
            articles = json.load(f)
        
        for article in articles:
            content = article['article_content']
            
            # Find all markdown links
            import re
            links = re.findall(r'\[([^\]]+)\]\(([^)]+)\)', content)
            
            for link_text, link_url in links:
                # Check link format
                assert link_text, f"Empty link text in {article['bill_id']}"
                assert link_url, f"Empty link URL in {article['bill_id']}"
                
                # Check for Congress.gov links
                if 'congress.gov' in link_url:
                    assert link_url.startswith('https://'), f"Non-HTTPS Congress.gov link: {link_url}"


class TestIntegrationSmoke:
    """
    /**
     * Integration-level smoke tests to ensure components interoperate.
     */
    """
    
    def test_all_components_importable(self):
        """
        /**
         * Validate that core components can be imported without errors.
         */
        """
        try:
            from controller import NewsGenerationController
            from workers.question_worker import QuestionWorker
            from workers.link_checker import LinkChecker
            from workers.article_generator import ArticleGenerator
            from services.congress_api import CongressAPIClient
            from services.state_manager import StateManager
            from utils.schemas import TARGET_BILLS, QuestionType
            from utils.kafka_client_simple import KafkaProducer, KafkaConsumer
        except ImportError as e:
            pytest.fail(f"Failed to import component: {e}")
    
    def test_schema_validation(self):
        """
        /**
         * Sanity-check pydantic model validation for a GeneratedArticle.
         */
        """
        from utils.schemas import GeneratedArticle
        
        # Test valid article
        valid_article = {
            "bill_id": "H.R.1",
            "bill_title": "Test Bill",
            "sponsor_bioguide_id": "T123456",
            "bill_committee_ids": ["hsii00"],
            "article_content": "## Test Article\n\nThis is a test.",
            "word_count": 10,
            "link_count": 0,
            "generated_at": 1234567890.0
        }
        
        article = GeneratedArticle(**valid_article)
        assert article.bill_id == "H.R.1"
        assert article.word_count == 10


if __name__ == "__main__":
    # Run smoke tests
    pytest.main([__file__, "-v"])
