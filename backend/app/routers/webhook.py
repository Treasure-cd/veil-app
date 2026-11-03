from fastapi import APIRouter, Request, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from loguru import logger
from uuid import uuid4, UUID
from datetime import datetime
import re
import base58
from core.session import get_session
from app.models.merchant import OnboardingStage, Merchant
from app.models.user import User
from app.models.payment import PaymentIntent
from app.services.message_service import send_msg
from app.services.merchant_service import create_merchant

router = APIRouter(
    prefix="/webhook",
    tags=["webhook"],
)

def is_valid_solana_address(address: str) -> bool:
    try:
        decoded = base58.b58decode(address.strip())
        return len(decoded) == 32
    except Exception:
        return False

def parse_invoice_message(message: str) -> dict | None:
    text = message.strip()
    
    # Pattern 1: Invoice [amount] [currency] [for] [description]
    # e.g. "Invoice 50 USDC for consulting"
    pattern1 = r"invoice\s+([\d,.]+)\s*(usdc|sol|usdg)(?:\s+for)?\s+(.+)"
    match1 = re.search(pattern1, text, re.IGNORECASE)
    if match1:
        amount = float(match1.group(1).replace(",", ""))
        currency = match1.group(2).upper()
        description = match1.group(3).strip()
        return {"amount": amount, "currency": currency, "description": description}

    # Pattern 2: Invoice [for] [description] of [amount] [currency]
    # e.g. "Invoice for consulting of 50 USDC"
    pattern2 = r"invoice\s+(?:for\s+)?(.+?)\s+(?:of|amount|value|for)?\s*([\d,.]+)\s*(usdc|sol|usdg)"
    match2 = re.search(pattern2, text, re.IGNORECASE)
    if match2:
        description = match2.group(1).strip()
        amount = float(match2.group(2).replace(",", ""))
        currency = match2.group(3).upper()
        return {"amount": amount, "currency": currency, "description": description}

    return None

@router.post("/whatsapp")
async def whatsapp_webhook(
    req: Request, 
    db: AsyncSession = Depends(get_session)
):
    """webhook to receive whatsapp's event"""
    
    logger.info("listening for events....")
    resp = await req.json()

    if resp.get("event") != "messages.upsert":
        logger.info(f'ignoring event: {resp.get("event")}, no messages appeared on whatsapp...')
        return {"status": "ignored"}
    
    data = resp["data"]["messages"]
    from_me = data["key"]["fromMe"]
    phone_number = data["key"]["cleanedSenderPn"]
    message = data.get("messageBody", "").strip()

    if from_me:
        logger.info('ignoring message sent by the merchant...')
        return {"status": "ignored"}
    
    # Find or create merchant
    merchant, created = await create_merchant(
        phone_number, 
        db
    )

    if created:
        try:
            welcome_msg = (
                "👋 Welcome to Veil!\n\n"
                "Solana's private payment and payroll solution, settled instantly in crypto and powered by Umbra privacy protocol.\n\n"
                "Let's get your business set up.\n\n"
                "🏪 What is the name of your business?"
            )
            await send_msg(phone_number, welcome_msg)
            logger.success(f"sent welcome message to +{phone_number}")
            return {"status": "ok"}
        except Exception as e:
            logger.error(f"failed to send welcome message: {str(e)}")
            return {"status": "error", "detail": "failed to send welcome message"}

    # Handle reset command
    clean_msg = message.lower()
    if clean_msg == "reset" or clean_msg == "restart":
        merchant.onboarding_stage = OnboardingStage.BUSINESS_NAME
        merchant.business_name = None
        merchant.business_type = None
        merchant.wallet_address = None
        merchant.updated_at = datetime.utcnow()
        db.add(merchant)
        await db.commit()
        await send_msg(phone_number, "🔄 Onboarding restarted.\n\n🏪 What is the name of your business?")
        return {"status": "ok"}

    # Handle stages
    if merchant.onboarding_stage == OnboardingStage.BUSINESS_NAME:
        merchant.business_name = message
        merchant.onboarding_stage = OnboardingStage.BUSINESS_TYPE
        merchant.updated_at = datetime.utcnow()
        db.add(merchant)
        await db.commit()

        business_msg = (
            "Great! 👍\n\n"
            "What type of business do you run?\n\n"
            "Examples:\n"
            "- Grocery / Provision Store\n"
            "- Pharmacy\n"
            "- Electronics\n"
            "- Fashion\n"
            "- Restaurant\n"
            "- Wholesale\n"
            "- Agriculture\n"
            "- Other\n\n"
            "Just reply with the business type."
        )
        await send_msg(phone_number, business_msg)
        return {"status": "ok"}
    
    if merchant.onboarding_stage == OnboardingStage.BUSINESS_TYPE:
        # Save business type and ask for wallet address
        merchant.business_type = message
        # We define WALLET_ADDRESS as an intermediate stage
        # To avoid enum mismatch, let's update merchant.py model or set onboarding_stage = "wallet_address"
        merchant.onboarding_stage = "wallet_address"
        merchant.updated_at = datetime.utcnow()
        db.add(merchant)
        await db.commit()

        wallet_msg = (
            "Excellent! 💎\n\n"
            "Finally, what Solana wallet address would you like to receive payments at?\n\n"
            "Please reply with a valid Solana public key (e.g. 5hz...)."
        )
        await send_msg(phone_number, wallet_msg)
        return {"status": "ok"}
        
    if merchant.onboarding_stage == "wallet_address":
        address = message.strip()
        if not is_valid_solana_address(address):
            err_msg = (
                "❌ Oops! That doesn't look like a valid Solana address.\n\n"
                "Please reply with a valid Solana public key (e.g. 5hz...)."
            )
            await send_msg(phone_number, err_msg)
            return {"status": "ok"}

        merchant.wallet_address = address
        merchant.onboarding_stage = OnboardingStage.COMPLETED
        merchant.updated_at = datetime.utcnow()
        db.add(merchant)
        await db.commit()

        success_msg = (
            "🎉 Setup Complete!\n\n"
            "Your business is registered. You can now generate invoice links directly in this chat.\n\n"
            "Try sending: 'Invoice 25,000 Naira for 3 pairs of shoes' or 'Invoice 50 USDC for consulting'.\n\n"
            "Reply with 'reset' anytime to update your settings."
        )
        await send_msg(phone_number, success_msg)
        return {"status": "ok"}

    if merchant.onboarding_stage == OnboardingStage.COMPLETED:
        parsed = parse_invoice_message(message)
        if not parsed:
            help_msg = (
                "🤔 I didn't quite catch that.\n\n"
                "To generate a payment link, please write in this format:\n"
                "'Invoice [amount] [currency] for [description]'\n\n"
                "Example:\n"
                "'Invoice 50 USDC for consulting'\n\n"
                "Supported currencies: USDC, SOL, USDG.\n\n"
                "Reply with 'reset' to change your wallet/business details."
            )
            await send_msg(phone_number, help_msg)
            return {"status": "ok"}

        target_currency = parsed["currency"]
        final_amount = parsed["amount"]

        # Determine mint and decimals
        mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v" # Default USDC
        decimals = 6
        if target_currency == "SOL":
            mint = "So11111111111111111111111111111111111111112"
            decimals = 9
        elif target_currency == "USDG":
            mint = "USDG_MINT_ADDRESS_HERE"
            decimals = 6

        amount_atomic = str(int(round(final_amount * (10 ** decimals))))

        # Find or create a user in User table for this wallet address
        stmt_u = select(User).where(User.address == merchant.wallet_address)
        res_u = await db.execute(stmt_u)
        user = res_u.scalars().first()

        if not user:
            user = User(
                address=merchant.wallet_address,
                nonce=None,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)

        # Create payment intent
        intent = PaymentIntent(
            user_id=user.id,
            merchant_ref=parsed["description"],
            mint=mint,
            amount_atomic=amount_atomic,
            recipient_address=merchant.wallet_address,
            receive_mode="private",
            memo=parsed["description"],
            status="created",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.add(intent)
        await db.commit()
        await db.refresh(intent)

        # Send the payment link back to the merchant on WhatsApp
        pay_link = f"http://localhost:3000/app/checkout/{intent.id}"
        reply_msg = (
            f"⚡ Payment Link Generated!\n\n"
            f"📋 *Invoice Details*\n"
            f"- Business: {merchant.business_name}\n"
            f"- Description: {parsed['description']}\n"
            f"- Amount: {parsed['amount']:,} {parsed['currency']}\n\n"
            f"🔗 *Share checkout link with customer*:\n"
            f"{pay_link}"
        )
        await send_msg(phone_number, reply_msg)

    return {"status": "ok"}