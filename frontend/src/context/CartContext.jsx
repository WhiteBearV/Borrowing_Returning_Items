import { createContext, useContext } from 'react'
import { useBorrowCart } from '../hooks/useBorrowCart.js'

const CartContext = createContext(null)

export function CartProvider({ children }) {
  const cart = useBorrowCart()
  return <CartContext.Provider value={cart}>{children}</CartContext.Provider>
}

export function useCart() {
  const ctx = useContext(CartContext)
  if (!ctx) throw new Error('useCart must be used inside CartProvider')
  return ctx
}
