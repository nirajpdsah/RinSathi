# tests/test_identity_agent.py
# Quick test to verify Identity Agent works end to end.
# Run with: python tests/test_identity_agent.py
# (Server must be running: uvicorn main:app --reload)

import asyncio
import uuid
from agents.shared_state import SharedState
from agents.identity_agent import IdentityAgent

agent = IdentityAgent()


async def test(label: str, nin: str):
    state = SharedState(
        applicant_id=uuid.uuid4(),
        loan_amount_npr=250000,
        sector="agriculture",
        nin=nin
    )
    result = await agent.run(state)
    print(f"\n{'='*50}")
    print(f"TEST: {label}")
    print(f"  NIN:              {nin}")
    print(f"  document_verified:{result.document_verified}")
    print(f"  doc_confidence:   {result.doc_confidence}")
    print(f"  verified_name:    {result.verified_full_name}")
    print(f"  citizenship_no:   {result.citizenship_no}")
    print(f"  land_parcels:     {result.total_land_parcels}")
    print(f"  land_total:       {result.total_land_ropani}R {result.total_land_aana}A")
    print(f"  manual_review:    {result.manual_review_required}")


async def main():
    # Test 1: Happy path — valid NIN with land
    await test("Valid NIN with land assets", "NID-001")

    # Test 2: Deceased NIN — should fail gracefully
    await test("Deceased NIN", "NID-049")

    # Test 3: NIN not in database
    await test("Non-existent NIN", "NID-999")

    # Test 4: Valid NIN but zero land ownership
    await test("Valid NIN, zero land", "NID-050")


if __name__ == "__main__":
    asyncio.run(main())