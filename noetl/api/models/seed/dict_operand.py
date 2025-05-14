from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from noetl.api.models.dict_operand import DictOperand

async def seed_dict_operand(session: AsyncSession) -> None:
    operand_definitions = [
        DictOperand(
            operand_name="register",
            description="Registers an internal component."
        ),
        DictOperand(
            operand_name="initialize",
            description="Initializes an internal component."
        ),
        DictOperand(
            operand_name="trigger",
            description="Triggers execution within the system."
        ),
        DictOperand(
            operand_name="persist",
            description="Persists data related to an internal component."
        ),
        DictOperand(
            operand_name="process",
            description="Processes execution and results."
        ),
        DictOperand(
            operand_name="close",
            description="Finalizes an internal component."
        ),
    ]

    existing_operands = await session.exec(select(DictOperand))
    existing_operand_names = {o.operand_name for o in existing_operands.all()}

    new_operands = [
        operand for operand in operand_definitions
        if operand.operand_name not in existing_operand_names
    ]

    session.add_all(new_operands)
    await session.commit()