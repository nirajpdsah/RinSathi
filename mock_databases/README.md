# Mock Government Databases — RinSathi ACLO

These SQLite databases simulate Nepal government systems for defense and demo.

## donidcr.db — Department of National ID and Civil Registration
- 50 citizen records across all 7 provinces
- Mirrors real NID card fields exactly
- NID-049: inactive NID (demonstrates KYC rejection)
- NID-050: valid NID with zero land ownership

## nelis.db — Nepal Land Information System  
- 80 land parcel records (Lalpurja data)
- Queried using citizenship_no from DoNIDCR response
- NID-050 owns no parcels (demonstrates zero-asset path)

## Demo Flow
1. User enters NIN (e.g. NID-001)
2. System queries donidcr.db → returns identity + citizenship_no
3. System queries nelis.db using citizenship_no → returns all land parcels
4. Pipeline continues with verified identity and asset data

## Production Note
Real integration requires NRB-mediated API agreements with:
- DoNIDCR: Department of National ID and Civil Registration
- NeLIS: Department of Land Management and Records
This is planned for post-defense production deployment.